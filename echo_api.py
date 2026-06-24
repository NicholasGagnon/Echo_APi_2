import os
import io
import re
import json
import base64
import threading
import requests as _requests_lib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from google import genai
from google.genai import types
from openai import OpenAI
from dotenv import load_dotenv

from prompts import generate_system_prompt

load_dotenv()

app = Flask(__name__)
CORS(app)

MODELS = {
    "gemini_free_1":        "gemini-2.0-flash-lite",
    "gemini_free_2":        "gemini-2.5-flash-lite",
    "deepseek":             "deepseek/DeepSeek-V3-0324",
    "kimi":                 "moonshotai/kimi-k2-freeplay",
    "nemotron":             "nvidia/nemotron-3-super-120b-a12b:free",
    "glm":                  "zai-org/glm-4-32b:free",
    "compound":             "compound-beta",
    "gemini_paid_founder":  "gemini-2.5-flash",
    "gemini_paid_ultra":    "gemini-2.0-flash-lite",
    "gemini_paid_standard": "gemini-2.5-flash-lite",
}

API_KEY_FREE          = os.getenv("API_KEY_FREE", "").strip()
API_KEY_PAID          = os.getenv("API_KEY_PAID", "").strip()
OPENROUTER_API_KEY    = os.getenv("OPENROUTER_API_KEY", "").strip()
GITHUB_API_KEY        = os.getenv("GITHUB_API_KEY", "").strip()
NVIDIA_API_KEY        = os.getenv("NVIDIA_API_KEY", "").strip()
GROQ_API_KEY          = os.getenv("GROQ_API_KEY", "").strip()
CLOUDFLARE_API_TOKEN  = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GITHUB_BASE_URL     = "https://models.github.ai/inference"
NVIDIA_BASE_URL     = "https://integrate.api.nvidia.com/v1"
GROQ_BASE_URL       = "https://api.groq.com/openai/v1"
CLOUDFLARE_BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"

client_gemini_free  = genai.Client(api_key=API_KEY_FREE)  if API_KEY_FREE  else None
client_gemini_paid  = genai.Client(api_key=API_KEY_PAID)  if API_KEY_PAID  else None
client_openrouter   = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
client_github       = OpenAI(base_url=GITHUB_BASE_URL,     api_key=GITHUB_API_KEY)     if GITHUB_API_KEY     else None
client_nvidia       = OpenAI(base_url=NVIDIA_BASE_URL,     api_key=NVIDIA_API_KEY)     if NVIDIA_API_KEY     else None
client_groq         = OpenAI(base_url=GROQ_BASE_URL,       api_key=GROQ_API_KEY)       if GROQ_API_KEY       else None
client_cloudflare   = OpenAI(base_url=CLOUDFLARE_BASE_URL, api_key=CLOUDFLARE_API_TOKEN) if CLOUDFLARE_API_TOKEN else None

_cf_session = _requests_lib.Session()

GLOBAL_FAILOVER_MEMORY_COUNT = 0
MAX_FREE_FAILOVERS = 200

def get_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    return GLOBAL_FAILOVER_MEMORY_COUNT

def increment_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    GLOBAL_FAILOVER_MEMORY_COUNT += 1
    print(f"[FAILOVER] {GLOBAL_FAILOVER_MEMORY_COUNT} / {MAX_FREE_FAILOVERS}")

MODELS_LOCK_REGISTRY = {}

def is_model_locked(model_key: str) -> bool:
    lock_time = MODELS_LOCK_REGISTRY.get(model_key)
    if lock_time:
        if datetime.now() < lock_time:
            return True
        else:
            del MODELS_LOCK_REGISTRY[model_key]
    return False

def lock_model(model_key: str):
    MODELS_LOCK_REGISTRY[model_key] = datetime.now() + timedelta(seconds=60)
    print(f"[LOCK] {model_key} hors circuit 60s.")

VALID_TIERS = {"connected_free", "basic", "premium", "ultra", "founder"}

def normalize_tier(raw: str) -> str:
    cleaned = (raw or "").lower().strip()
    if cleaned in VALID_TIERS: return cleaned
    if cleaned == "free":      return "connected_free"
    if "founder" in cleaned:   return "founder"
    if "ultra"   in cleaned:   return "ultra"
    if "premium" in cleaned:   return "premium"
    if "basic"   in cleaned:   return "basic"
    return "connected_free"

ERR_QUOTA   = {"action": None, "response": "Le service est temporairement sature. Reessaie dans quelques instants."}
ERR_FINAL   = {"action": None, "response": "Tous les serveurs sont momentanement indisponibles. Reessaie dans 1 minute."}
ERR_CRASH   = {"action": None, "response": "Une erreur inattendue s'est produite. Reessaie dans quelques secondes."}
ERR_HORIZON = {"response": "Le moteur de recherche est temporairement indisponible.", "attributes": [], "matrix": None}

def clean_and_parse_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"):   text = text[3:]
    if text.endswith("```"):       text = text[:-3]
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "response" in parsed:
            return parsed
    except Exception:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and "response" in parsed:
                return parsed
        except Exception:
            pass
    if text:
        clean_response = text
        if '"response":' in text:
            res_match = re.search(r'"response"\s*:\s*"([^"]+)"', text)
            if res_match:
                clean_response = res_match.group(1)
        return {"action": None, "response": clean_response}
    raise ValueError("Reponse vide.")

def clean_and_parse_horizon_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"):   text = text[3:]
    if text.endswith("```"):       text = text[:-3]
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {"response": text, "attributes": [], "matrix": None}

def build_gemini_contents(historique_reduit, image_b64, user_message, force_neutral_style):
    contents = []
    for msg in historique_reduit:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"):
            continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or clean_content == "...":
            continue
        if msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception:
                pass
            if force_neutral_style:
                clean_content = "[Analyse technique archivee]"
            contents.append({"role": "model", "parts": [types.Part.from_text(text=clean_content)]})
        elif msg.startswith("You:") or msg.startswith("Toi:"):
            clean_content = re.sub(r'\s{3,}', ' ', clean_content).strip()
            contents.append({"role": "user", "parts": [types.Part.from_text(text=clean_content)]})
    last_parts = []
    if image_b64:
        try:
            header, b64data = image_b64.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]
            raw_bytes = base64.b64decode(b64data)
            last_parts.append(types.Part.from_bytes(data=raw_bytes, mime_type=mime_type))
        except Exception as e:
            print(f"[WARN] Image error: {e}")
    last_parts.append(types.Part.from_text(text=user_message or "Analyse cette image."))
    contents.append({"role": "user", "parts": last_parts})
    return contents

def prepare_shared_context(data, source_override=None):
    user_message     = data.get("message", "")
    calendar_events  = data.get("calendarEvents", {})
    raw_history      = data.get("history", [])
    memory_summary   = data.get("summary", "")
    source           = source_override if source_override else data.get("source", "chat").lower().strip()
    image_b64        = data.get("image", None)
    selected_buttons = data.get("selectedButtons", [])
    current_expenses = data.get("currentExpenses", [])
    current_calories = data.get("currentCalories", [])
    current_cycle    = data.get("currentCycle", "mois")
    user_tier        = normalize_tier(data.get("userTier", "connected_free"))

    maintenant      = datetime.now()
    date_aujourdhui = maintenant.strftime("%A %d %B %Y")
    annee_en_cours  = maintenant.strftime("%Y")

    filtered_calendar = {}
    date_debut = (maintenant - timedelta(days=31)).date()
    date_fin   = maintenant.date()
    try:
        for date_str, events in calendar_events.items():
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                date_evt = datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_debut <= date_evt <= date_fin:
                    filtered_calendar[date_str] = events
            else:
                filtered_calendar[date_str] = events
    except Exception as e:
        print(f"[WARN] Calendrier: {e}")
        filtered_calendar = calendar_events

    base_system_prompt = generate_system_prompt(
        source=source,
        selected_buttons=selected_buttons,
        date_aujourdhui=date_aujourdhui,
        annee_en_cours=annee_en_cours,
        user_tier=user_tier,
        filtered_calendar=filtered_calendar,
        current_expenses=current_expenses,
        current_calories=current_calories,
        current_cycle=current_cycle
    )

    system_prompt = base_system_prompt

    if memory_summary and user_tier not in ("connected_free", "basic"):
        system_prompt += (
            "\n\nLONG TERM MEMORY\n"
            "================\n"
            f"{memory_summary}\n"
        )

    system_prompt += "\n\nCRITICAL SAFETY DIRECTIVE: Only trigger actions explicitly demanded in the LATEST message."

    taille_memoire    = 30 if user_tier in ["ultra", "founder"] else (15 if user_tier in ["basic", "premium"] else 5)
    output_tokens     = 4096 if user_tier in ["ultra", "founder"] else (2048 if user_tier in ["basic", "premium"] else 1024)
    historique_ajuste = raw_history[-taille_memoire:]
    force_neutral     = len(selected_buttons) > 0 or source == "vitality"
    gemini_contents   = build_gemini_contents(historique_ajuste, image_b64, user_message, force_neutral)

    messages_openai = [{"role": "system", "content": system_prompt}]
    for msg in historique_ajuste:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"):
            continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or clean_content == "...":
            continue
        if msg.startswith("You:") or msg.startswith("Toi:"):
            clean_content = re.sub(r'\s{3,}', ' ', clean_content).strip()
            messages_openai.append({"role": "user", "content": clean_content})
        elif msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception:
                pass
            messages_openai.append({"role": "assistant", "content": clean_content})
    if user_message:
        messages_openai.append({"role": "user", "content": user_message})

    return {
        "system_prompt":   system_prompt,
        "output_tokens":   output_tokens,
        "gemini_contents": gemini_contents,
        "messages_openai": messages_openai,
        "user_tier":       user_tier,
    }

def call_with_timeout(fn, timeout_sec):
    result = [None]
    error  = [None]
    def target():
        try:
            result[0] = fn()
        except Exception as e:
            error[0] = e
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise TimeoutError(f"Timeout apres {timeout_sec}s")
    if error[0]:
        raise error[0]
    return result[0]

def call_gemini(client, model_key, ctx, timeout=25):
    def fn():
        return client.models.generate_content(
            model=MODELS[model_key],
            contents=ctx["gemini_contents"],
            config=types.GenerateContentConfig(
                system_instruction=ctx["system_prompt"],
                max_output_tokens=ctx["output_tokens"],
                temperature=0.1,
            )
        )
    return call_with_timeout(fn, timeout)

def call_openai(client, model_key, ctx, temp=0.1, timeout=20.0):
    model_name = MODELS[model_key]
    if model_name.startswith("@cf/"):
        cf_account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        cf_token   = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run/{model_name}"
        r = _cf_session.post(
            url,
            json={"messages": ctx["messages_openai"][1:]},
            headers={"Authorization": f"Bearer {cf_token}"},
            timeout=timeout
        )
        r.raise_for_status()
        return r.json()["result"]["response"]
    res = client.chat.completions.create(
        model=model_name,
        messages=ctx["messages_openai"],
        temperature=temp,
        timeout=timeout
    )
    return res.choices[0].message.content

def run_paid_cascade(ctx):
    tier = ctx["user_tier"]
    if tier == "founder":
        primary, fallback = "gemini_paid_founder",  "gemini_paid_standard"
    elif tier == "ultra":
        primary, fallback = "gemini_paid_ultra",    "gemini_paid_standard"
    else:
        primary, fallback = "gemini_paid_standard", "gemini_paid_ultra"
    try:
        r = call_gemini(client_gemini_paid, primary, ctx, timeout=25)
        return clean_and_parse_json(r.text)
    except Exception as e:
        print(f"[PAID] Echec {primary} ({e}), bascule {fallback}")
    try:
        r = call_gemini(client_gemini_paid, fallback, ctx, timeout=25)
        return clean_and_parse_json(r.text)
    except Exception as e:
        print(f"[PAID] Echec {fallback} ({e})")
    return ERR_FINAL

def run_free_cascade(steps, ctx, parser=None):
    if parser is None:
        parser = clean_and_parse_json
    if get_failover_count() >= MAX_FREE_FAILOVERS:
        return ERR_QUOTA
    for i, (client, model_key, timeout) in enumerate(steps):
        if client is None:
            continue
        if is_model_locked(model_key):
            continue
        is_last = (i == len(steps) - 1)
        try:
            if client in (client_gemini_free, client_gemini_paid):
                r      = call_gemini(client, model_key, ctx, timeout=timeout)
                result = parser(r.text)
            else:
                r      = call_openai(client, model_key, ctx, temp=0.1, timeout=float(timeout))
                result = parser(r)
            if is_last:
                increment_failover_count()
            return result
        except Exception as e:
            print(f"[FREE] Echec {model_key} ({e})")
            lock_model(model_key)
    return ERR_FINAL

# ── HORIZON — cascade dédiée ───────────────────────────────────────────────────
# Ordre : Kimi (OpenRouter free) → GLM (OpenRouter free) → Gemini 2.5 flash-lite (payant)
# Nemotron retiré : trop hallucinateur sur les données locales
def get_horizon_steps(user_tier: str):
    """
    Retourne la cascade de modèles pour Horizon selon le tier.
    Payant : Gemini 2.5 flash-lite directement.
    Gratuit : Kimi → GLM → Gemini 2.5 flash-lite (fallback payant).
    """
    if user_tier != "connected_free":
        return [
            (client_gemini_paid, "gemini_paid_standard", 30),
        ]
    return [
        (client_openrouter, "kimi",                 25),  # Kimi K2 freeplay — bon sur données structurées
        (client_openrouter, "glm",                  25),  # GLM-4 32B free — solide fallback
        (client_gemini_paid, "gemini_paid_standard", 30), # Gemini 2.5 flash-lite — fallback payant fiable
    ]

def extract_horizon_result(query: str, ctx: dict, attempt: int = 1) -> dict:
    """
    Cascade Horizon avec retry automatique.
    Chaque modèle a une seule chance. Si la structure JSON est incomplète → modèle suivant.
    """
    required_matrix_keys = [
        "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible",
        "qu_en_pensent_les_gens", "quelles_sont_les_alternatives",
        "quels_sont_les_risques", "quelle_option_est_recommandee"
    ]

    steps = get_horizon_steps(ctx["user_tier"])

    if attempt > len(steps):
        print("[HORIZON] Tous les modèles épuisés.")
        return ERR_HORIZON

    client, model_key, timeout = steps[attempt - 1]

    if client is None:
        print(f"[HORIZON] Client None pour {model_key}, passage au suivant.")
        return extract_horizon_result(query, ctx, attempt + 1)

    if is_model_locked(model_key):
        print(f"[HORIZON] {model_key} verrouillé, passage au suivant.")
        return extract_horizon_result(query, ctx, attempt + 1)

    try:
        print(f"[HORIZON] Tentative {attempt}/{len(steps)} — {model_key}")

        if client in (client_gemini_free, client_gemini_paid):
            r      = call_gemini(client, model_key, ctx, timeout=timeout)
            parsed = clean_and_parse_horizon_json(r.text)
        else:
            r      = call_openai(client, model_key, ctx, temp=0.1, timeout=float(timeout))
            parsed = clean_and_parse_horizon_json(r)

        # Validation de structure
        has_response   = bool(parsed.get("response", "").strip())
        has_attributes = isinstance(parsed.get("attributes"), list) and len(parsed["attributes"]) > 0
        has_matrix     = (
            isinstance(parsed.get("matrix"), dict)
            and all(k in parsed["matrix"] for k in required_matrix_keys)
        )

        if not has_response:
            print(f"[HORIZON] {model_key} — réponse vide, modèle suivant.")
            lock_model(model_key)
            return extract_horizon_result(query, ctx, attempt + 1)

        # Si matrix incomplète mais réponse présente → on accepte avec matrix=None
        # (évite de perdre une bonne réponse pour un JSON mal formé)
        if not has_matrix:
            print(f"[HORIZON] {model_key} — matrix incomplète, réponse conservée sans matrix.")
            parsed["matrix"] = None

        if not has_attributes:
            parsed["attributes"] = []

        # Incrémenter failover seulement si on est sur le modèle payant en dernier recours
        if model_key == "gemini_paid_standard" and ctx["user_tier"] == "connected_free":
            increment_failover_count()

        print(f"[HORIZON] Succès — {model_key}")
        return parsed

    except Exception as e:
        print(f"[HORIZON] Erreur {model_key} ({e}), modèle suivant.")
        lock_model(model_key)
        return extract_horizon_result(query, ctx, attempt + 1)


@app.route("/ping")
def ping():
    return jsonify({"status": "awake"})

@app.route("/export", methods=["POST"])
def export_route():
    data  = request.get_json(silent=True) or {}
    fmt   = (data.get("format") or "").lower().strip()
    title = (data.get("title")  or "Document Echo AI").strip()
    html  = (data.get("html")   or "").strip()
    if not html:
        return jsonify({"error": "Contenu vide."}), 400
    safe = "".join(c for c in title if c.isalnum() or c in " _-").strip().replace(" ", "_") or "document"
    try:
        if fmt == "txt":
            txt = re.sub(r'<[^>]+>', '', html).replace('&nbsp;', ' ').replace('&amp;', '&')
            return send_file(io.BytesIO(txt.encode("utf-8")), mimetype="text/plain", as_attachment=True, download_name=f"{safe}.txt")
        elif fmt == "pdf":
            try:
                from xhtml2pdf import pisa
                styled = f"<html><head><meta charset=\"utf-8\"><style>body{{font-family:sans-serif;font-size:11pt;line-height:1.6;color:#18181b}}h1{{font-size:22pt;border-bottom:1px solid #e4e4e7;padding-bottom:8px}}p{{margin-bottom:12px;text-align:justify}}</style></head><body><h1>{title}</h1>{html}</body></html>"
                buf = io.BytesIO()
                pisa.CreatePDF(io.StringIO(styled), dest=buf)
                buf.seek(0)
                return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=f"{safe}.pdf")
            except ImportError:
                return jsonify({"error": "xhtml2pdf non installe."}), 503
        elif fmt == "docx":
            try:
                from docx import Document
                from docx.shared import Pt, RGBColor
                from docx.enum.text import WD_ALIGN_PARAGRAPH
                doc = Document()
                t = doc.add_paragraph(); r = t.add_run(title)
                r.font.size = Pt(24); r.font.bold = True; r.font.color.rgb = RGBColor(15, 23, 42)
                clean = re.sub(r'<[^>]+>', '\n', html).replace('&nbsp;', ' ')
                for line in clean.split('\n'):
                    line = line.strip()
                    if line:
                        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                        run = p.add_run(line); run.font.size = Pt(11)
                buf = io.BytesIO(); doc.save(buf); buf.seek(0)
                return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document", as_attachment=True, download_name=f"{safe}.docx")
            except ImportError:
                return jsonify({"error": "python-docx non installe."}), 503
        elif fmt == "epub":
            try:
                from ebooklib import epub
                book = epub.EpubBook()
                book.set_identifier(f"echo-{int(datetime.now().timestamp())}")
                book.set_title(title); book.set_language("fr"); book.add_author("Echo AI")
                ch = epub.EpubHtml(title=title, file_name="ch1.xhtml", lang="fr")
                ch.content = f"<html><body><h1>{title}</h1>{html}</body></html>"
                book.add_item(ch); book.toc = (epub.Link("ch1.xhtml", title, "ch1"),)
                book.spine = ["nav", ch]; book.add_item(epub.EpubNav()); book.add_item(epub.EpubNcx())
                buf = io.BytesIO(); epub.write_epub(buf, book, {}); buf.seek(0)
                return send_file(buf, mimetype="application/epub+zip", as_attachment=True, download_name=f"{safe}.epub")
            except ImportError:
                return jsonify({"error": "EbookLib non installe."}), 503
        else:
            return jsonify({"error": f"Format '{fmt}' non supporte."}), 400
    except Exception as e:
        print(f"[EXPORT ERROR] {fmt}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/home", methods=["POST"])
def home():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="home")
        if ctx["user_tier"] != "connected_free":
            return jsonify(run_paid_cascade(ctx))
        steps = [
            (client_gemini_free, "gemini_free_2",        8),
            (client_cloudflare,  "glm",                  8),
            (client_gemini_free, "gemini_free_1",        8),
            (client_gemini_paid, "gemini_paid_standard", 25),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /home: {e}")
        return jsonify(ERR_CRASH), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="chat")
        if ctx["user_tier"] != "connected_free":
            return jsonify(run_paid_cascade(ctx))
        steps = [
            (client_gemini_free, "gemini_free_1",        8),
            (client_openrouter,  "kimi",                 8),
            (client_gemini_free, "gemini_free_2",        8),
            (client_gemini_paid, "gemini_paid_standard", 25),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /chat: {e}")
        return jsonify(ERR_CRASH), 500

@app.route("/vitality", methods=["POST"])
def vitality():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="vitality")
        if ctx["user_tier"] != "connected_free":
            return jsonify(run_paid_cascade(ctx))
        steps = [
            (client_groq,        "compound",             8),
            (client_cloudflare,  "glm",                  8),
            (client_gemini_paid, "gemini_paid_standard", 25),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /vitality: {e}")
        return jsonify(ERR_CRASH), 500

@app.route("/history", methods=["POST"])
def history():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="history")
        if ctx["user_tier"] != "connected_free":
            return jsonify(run_paid_cascade(ctx))
        steps = [
            (client_openrouter,  "kimi",                 8),
            (client_github,      "deepseek",             8),
            (client_groq,        "compound",             8),
            (client_gemini_paid, "gemini_paid_standard", 25),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /history: {e}")
        return jsonify(ERR_CRASH), 500

@app.route("/books", methods=["POST"])
def books():
    try:
        data       = request.json or {}
        message    = data.get("message", "").strip()
        history    = data.get("history", [])
        tier       = normalize_tier(data.get("userTier", "connected_free"))
        buttons    = data.get("selectedButtons", [])
        book_title = data.get("bookTitle", "")

        INJECT_KEYWORDS = ["inject", "injecte", "insere", "ecris ici", "write here", "add this"]
        wants_inject    = any(kw in message.lower() for kw in INJECT_KEYWORDS)

        mode_prompts = {
            "creative": "Tu es en mode Creatif. Genere du contenu litteraire original avec un style soigne.",
            "ideas":    "Tu es en mode Idees. Propose des pistes narratives et rebondissements.",
            "critical": "Tu es en mode Critique. Analyse le texte : rythme, coherence, clarte.",
        }
        active_mode      = buttons[0] if buttons else None
        mode_instruction = mode_prompts.get(active_mode, "Tu es un assistant d'ecriture creatif et polyvalent.")
        inject_instruction = ""
        if wants_inject:
            inject_instruction = (
                "\n\nL'utilisateur veut que tu INJECTES du texte dans son livre. "
                "Genere le passage et termine avec :\n<<<INJECT_TEXT>>>\n[texte propre sans HTML]\n<<<END_INJECT>>>"
            )
        system_prompt = f"{mode_instruction}{inject_instruction}\n\nLivre : \"{book_title}\". Reponds en moins de 400 mots. Sois direct et elegant."

        gemini_history = []
        for msg in history[-10:]:
            if msg.startswith("You: "):
                gemini_history.append(types.Content(role="user",  parts=[types.Part(text=msg[5:])]))
            elif msg.startswith("Echo: "):
                gemini_history.append(types.Content(role="model", parts=[types.Part(text=msg[6:])]))
        gemini_history.append(types.Content(role="user", parts=[types.Part(text=message)]))

        def run_books_call(client, model_key, timeout):
            if client in (client_gemini_free, client_gemini_paid):
                def fn():
                    return client.models.generate_content(
                        model=MODELS[model_key],
                        contents=gemini_history,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            max_output_tokens=1200,
                            temperature=0.85,
                        )
                    )
                resp = call_with_timeout(fn, timeout)
                return resp.text or ""
            else:
                openai_messages = [{"role": "system", "content": system_prompt}]
                for msg in history[-10:]:
                    if msg.startswith("You: "):
                        openai_messages.append({"role": "user",      "content": msg[5:]})
                    elif msg.startswith("Echo: "):
                        openai_messages.append({"role": "assistant", "content": msg[6:]})
                openai_messages.append({"role": "user", "content": message})
                res = client.chat.completions.create(
                    model=MODELS[model_key],
                    messages=openai_messages,
                    temperature=0.85,
                    timeout=float(timeout)
                )
                return res.choices[0].message.content or ""

        if tier in ("basic", "premium", "ultra", "founder"):
            paid_key = "gemini_paid_founder" if tier == "founder" else "gemini_paid_standard"
            try:
                full_text = run_books_call(client_gemini_paid, paid_key, 25)
            except Exception as e:
                print(f"[BOOKS PAID] Echec {paid_key} ({e})")
                full_text = ""
        else:
            if get_failover_count() >= MAX_FREE_FAILOVERS:
                return jsonify({"response": ERR_QUOTA["response"], "inject": False, "action": None})
            full_text   = ""
            books_steps = [
                (client_openrouter,  "kimi",                 10),
                (client_openrouter,  "glm",                  10),
                (client_gemini_paid, "gemini_paid_standard", 25),
            ]
            for i, (client, model_key, timeout) in enumerate(books_steps):
                if client is None or is_model_locked(model_key):
                    continue
                try:
                    full_text = run_books_call(client, model_key, timeout)
                    if i == len(books_steps) - 1:
                        increment_failover_count()
                    break
                except Exception as e:
                    print(f"[BOOKS FREE] Echec {model_key} ({e})")
                    lock_model(model_key)

        if not full_text:
            return jsonify({"response": ERR_FINAL["response"], "inject": False, "action": None})
        if wants_inject and "<<<INJECT_TEXT>>>" in full_text:
            parts      = full_text.split("<<<INJECT_TEXT>>>")
            response   = parts[0].strip()
            inject_raw = parts[1].split("<<<END_INJECT>>>")[0].strip() if len(parts) > 1 else ""
            return jsonify({"response": response or "Voici le passage.", "inject": True, "inject_text": inject_raw, "action": None})
        return jsonify({"response": full_text, "inject": False, "action": None})

    except Exception as e:
        print(f"Erreur /books: {e}")
        return jsonify({"response": ERR_CRASH["response"], "inject": False, "action": None}), 500

@app.route("/horizon", methods=["POST"])
def horizon():
    try:
        data  = request.json or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "L'intention d'exploration est vide."}), 400

        # Message enrichi : demande explicite de recherche web + JSON strict
        # "jusqu'à 10" pour éviter le remplissage artificiel
        data["message"] = (
            f"Recherche web complète sur : {query}\n\n"
            f"RÈGLE CRITIQUE : Retourne uniquement des informations réelles confirmées par ta recherche. "
            f"Si une donnée (adresse, prix, horaire, URL) n'est pas trouvée, écris le jeton approprié. "
            f"Retourne jusqu'à 10 résultats — moins si tu n'en confirmes pas davantage. "
            f"Réponds UNIQUEMENT en JSON valide avec les clés : response, attributes, matrix."
        )

        ctx = prepare_shared_context(data, source_override="horizonweb")

        if get_failover_count() >= MAX_FREE_FAILOVERS and ctx["user_tier"] == "connected_free":
            return jsonify(ERR_QUOTA)

        result = extract_horizon_result(query, ctx)
        return jsonify(result)

    except Exception as e:
        print(f"[HORIZON] Erreur critique: {e}")
        return jsonify(ERR_HORIZON), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)