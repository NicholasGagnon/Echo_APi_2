import os
import io
import re
import json
import base64
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

# ── CLÉS D'API ────────────────────────────────────────────────────────────────
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

# ── CLIENTS ───────────────────────────────────────────────────────────────────
client_gemini_free  = genai.Client(api_key=API_KEY_FREE)  if API_KEY_FREE  else None
client_gemini_paid  = genai.Client(api_key=API_KEY_PAID)  if API_KEY_PAID  else None
client_openrouter   = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
client_github       = OpenAI(base_url=GITHUB_BASE_URL,     api_key=GITHUB_API_KEY)     if GITHUB_API_KEY     else None
client_nvidia       = OpenAI(base_url=NVIDIA_BASE_URL,     api_key=NVIDIA_API_KEY)     if NVIDIA_API_KEY     else None
client_groq         = OpenAI(base_url=GROQ_BASE_URL,       api_key=GROQ_API_KEY)       if GROQ_API_KEY       else None
client_cloudflare   = OpenAI(base_url=CLOUDFLARE_BASE_URL, api_key=CLOUDFLARE_API_TOKEN) if CLOUDFLARE_API_TOKEN else None

# ── FILET DE SÉCURITÉ CONNECTED_FREE ─────────────────────────────────────────
GLOBAL_FAILOVER_MEMORY_COUNT = 0
MAX_FREE_FAILOVERS = 200

def get_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    return GLOBAL_FAILOVER_MEMORY_COUNT

def increment_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    GLOBAL_FAILOVER_MEMORY_COUNT += 1
    print(f"[FAILOVER FILET] {GLOBAL_FAILOVER_MEMORY_COUNT} / {MAX_FREE_FAILOVERS}")

# ── GESTION DES LOCKS DE MODELES ─────────────────────────────────────────────
MODELS_LOCK_REGISTRY = {}

def is_model_locked(model_name: str) -> bool:
    lock_time = MODELS_LOCK_REGISTRY.get(model_name)
    if lock_time:
        if datetime.now() < lock_time:
            return True
        else:
            del MODELS_LOCK_REGISTRY[model_name]
    return False

def lock_model(model_name: str):
    MODELS_LOCK_REGISTRY[model_name] = datetime.now() + timedelta(seconds=60)
    print(f"[LOCK] {model_name} hors circuit 60s.")

# ── NORMALISATION DU TIER ─────────────────────────────────────────────────────
VALID_TIERS = {"connected_free", "basic", "premium", "ultra", "founder"}

def normalize_tier(raw: str) -> str:
    cleaned = (raw or "").lower().strip()
    if cleaned in VALID_TIERS: return cleaned
    if cleaned == "free": return "connected_free"
    if "founder" in cleaned: return "founder"
    if "ultra"   in cleaned: return "ultra"
    if "premium" in cleaned: return "premium"
    if "basic"   in cleaned: return "basic"
    return "connected_free"

# ── JSON PARSER ───────────────────────────────────────────────────────────────
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

# ── JSON PARSER HORIZON (clés différentes) ────────────────────────────────────
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

# ── BUILD GEMINI CONTENTS ─────────────────────────────────────────────────────
def build_gemini_contents(historique_reduit, image_b64, user_message, force_neutral_style):
    contents = []
    for msg in historique_reduit:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"):
            continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or clean_content == "...":
            continue
        if msg.startswith("You:") or msg.startswith("Toi:"):
            contents.append({"role": "user", "parts": [types.Part.from_text(text=clean_content)]})
        elif msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception:
                pass
            if force_neutral_style:
                clean_content = "[Analyse technique archivee]"
            contents.append({"role": "model", "parts": [types.Part.from_text(text=clean_content)]})

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

# ── PREPARE SHARED CONTEXT ────────────────────────────────────────────────────
def prepare_shared_context(data, source_override=None):
    user_message     = data.get("message", "")
    calendar_events  = data.get("calendarEvents", {})
    raw_history      = data.get("history", [])
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
    system_prompt = base_system_prompt + (
        "\n\nCRITICAL SAFETY DIRECTIVE: Only trigger actions explicitly demanded in the LATEST message."
    )

    taille_memoire = 30 if user_tier in ["ultra", "founder"] else (15 if user_tier in ["basic", "premium"] else 5)
    output_tokens  = 4096 if user_tier in ["ultra", "founder"] else (2048 if user_tier in ["basic", "premium"] else 1024)
    historique_ajuste = raw_history[-taille_memoire:]
    force_neutral = len(selected_buttons) > 0 or source == "vitality"
    gemini_contents = build_gemini_contents(historique_ajuste, image_b64, user_message, force_neutral)

    messages_openrouter = [{"role": "system", "content": system_prompt}]
    for msg in historique_ajuste:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"):
            continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or clean_content == "...":
            continue
        if msg.startswith("You:") or msg.startswith("Toi:"):
            messages_openrouter.append({"role": "user", "content": clean_content})
        elif msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception:
                pass
            messages_openrouter.append({"role": "assistant", "content": clean_content})
    if user_message:
        messages_openrouter.append({"role": "user", "content": user_message})

    return {
        "system_prompt": system_prompt,
        "output_tokens": output_tokens,
        "gemini_contents": gemini_contents,
        "messages_openrouter": messages_openrouter,
        "user_tier": user_tier,
    }

# ── EXECUTEURS ────────────────────────────────────────────────────────────────
def execute_gemini_call(client, model, ctx):
    return client.models.generate_content(
        model=model,
        contents=ctx["gemini_contents"],
        config=types.GenerateContentConfig(
            system_instruction=ctx["system_prompt"],
            max_output_tokens=ctx["output_tokens"]
        )
    )

def execute_openai_call(client, model, ctx, temp=0.7, timeout=7.0):
    res = client.chat.completions.create(
        model=model,
        messages=ctx["messages_openrouter"],
        temperature=temp,
        timeout=timeout
    )
    return res.choices[0].message.content

# ── ROUTE /export ─────────────────────────────────────────────────────────────
@app.route("/export", methods=["POST"])
def export_route():
    data = request.get_json(silent=True) or {}
    fmt  = (data.get("format") or "").lower().strip()
    title = (data.get("title") or "Document Echo AI").strip()
    html  = (data.get("html") or "").strip()

    if not html:
        return jsonify({"error": "Contenu vide."}), 400

    safe = "".join(c for c in title if c.isalnum() or c in " _-").strip().replace(" ", "_") or "document"

    try:
        if fmt == "txt":
            txt = re.sub(r'<[^>]+>', '', html)
            txt = txt.replace('&nbsp;', ' ').replace('&amp;', '&')
            buf = io.BytesIO(txt.encode("utf-8"))
            return send_file(buf, mimetype="text/plain", as_attachment=True, download_name=f"{safe}.txt")

        elif fmt == "pdf":
            try:
                from xhtml2pdf import pisa
                styled = (
                    "<html><head><meta charset=\"utf-8\"><style>"
                    "body{font-family:sans-serif;font-size:11pt;line-height:1.6;color:#18181b}"
                    "h1{font-size:22pt;border-bottom:1px solid #e4e4e7;padding-bottom:8px}"
                    "p{margin-bottom:12px;text-align:justify}"
                    f"</style></head><body><h1>{title}</h1>{html}</body></html>"
                )
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
                t = doc.add_paragraph()
                r = t.add_run(title)
                r.font.size = Pt(24)
                r.font.bold = True
                r.font.color.rgb = RGBColor(15, 23, 42)
                clean = re.sub(r'<[^>]+>', '\n', html).replace('&nbsp;', ' ')
                for line in clean.split('\n'):
                    line = line.strip()
                    if line:
                        p = doc.add_paragraph()
                        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                        run = p.add_run(line)
                        run.font.size = Pt(11)
                buf = io.BytesIO()
                doc.save(buf)
                buf.seek(0)
                return send_file(
                    buf,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    as_attachment=True,
                    download_name=f"{safe}.docx"
                )
            except ImportError:
                return jsonify({"error": "python-docx non installe."}), 503

        elif fmt == "epub":
            try:
                from ebooklib import epub
                book = epub.EpubBook()
                book.set_identifier(f"echo-{int(datetime.now().timestamp())}")
                book.set_title(title)
                book.set_language("fr")
                book.add_author("Echo AI")
                ch = epub.EpubHtml(title=title, file_name="ch1.xhtml", lang="fr")
                ch.content = f"<html><body><h1>{title}</h1>{html}</body></html>"
                book.add_item(ch)
                book.toc = (epub.Link("ch1.xhtml", title, "ch1"),)
                book.spine = ["nav", ch]
                book.add_item(epub.EpubNav())
                book.add_item(epub.EpubNcx())
                buf = io.BytesIO()
                epub.write_epub(buf, book, {})
                buf.seek(0)
                return send_file(buf, mimetype="application/epub+zip", as_attachment=True, download_name=f"{safe}.epub")
            except ImportError:
                return jsonify({"error": "EbookLib non installe."}), 503

        else:
            return jsonify({"error": f"Format '{fmt}' non supporte."}), 400

    except Exception as e:
        print(f"[EXPORT ERROR] {fmt}: {e}")
        return jsonify({"error": str(e)}), 500

# ── ROUTE /chat ───────────────────────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json or {}
        ctx = prepare_shared_context(data, source_override="chat")

        if ctx["user_tier"] == "connected_free":
            if get_failover_count() >= MAX_FREE_FAILOVERS:
                return jsonify({"action": None, "response": "Ouf, mon sillage sature ! 😎"})

            model_1 = "gemini-2.0-flash-lite"
            if client_gemini_free and not is_model_locked(model_1):
                try:
                    r = execute_gemini_call(client_gemini_free, model_1, ctx)
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec {model_1} ({e})")
                    lock_model(model_1)

            model_2 = "gemini-2.5-flash-lite"
            if client_gemini_free and not is_model_locked(model_2):
                try:
                    r = execute_gemini_call(client_gemini_free, model_2, ctx)
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec {model_2} ({e})")
                    lock_model(model_2)

            if client_gemini_paid and not is_model_locked("gemini-2.5-flash-lite-paid"):
                try:
                    r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                    increment_failover_count()
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec filet ({e})")
                    lock_model("gemini-2.5-flash-lite-paid")

            return jsonify({"action": None, "response": "Sillage sature, reessaie ! 😎"})

        else:
            target = "gemini-2.0-flash" if ctx["user_tier"] == "founder" else "gemini-2.5-flash-lite"
            try:
                r = execute_gemini_call(client_gemini_paid, target, ctx)
                return jsonify(clean_and_parse_json(r.text))
            except Exception as e:
                print(f"Echec {target} ({e})")
                r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                return jsonify(clean_and_parse_json(r.text))

    except Exception as e:
        print(f"Erreur /chat: {e}")
        return jsonify({"action": None, "response": "Systeme instable, reessaie !"}), 500

# ── ROUTE /books ──────────────────────────────────────────────────────────────
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
        wants_inject = any(kw in message.lower() for kw in INJECT_KEYWORDS)

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
                "Genere le passage et termine avec :\n"
                "<<<INJECT_TEXT>>>\n[texte propre sans HTML]\n<<<END_INJECT>>>"
            )

        system_prompt = (
            f"{mode_instruction}{inject_instruction}\n\n"
            f"Livre : \"{book_title}\". Reponds en moins de 400 mots. Sois direct et elegant."
        )

        gemini_history = []
        for msg in history[-10:]:
            if msg.startswith("You: "):
                gemini_history.append(types.Content(role="user",  parts=[types.Part(text=msg[5:])]))
            elif msg.startswith("Echo: "):
                gemini_history.append(types.Content(role="model", parts=[types.Part(text=msg[6:])]))
        gemini_history.append(types.Content(role="user", parts=[types.Part(text=message)]))

        client = client_gemini_paid if tier in ("premium", "ultra", "founder") else client_gemini_free
        model  = "gemini-2.0-flash" if tier in ("premium", "ultra", "founder") else "gemini-2.0-flash-lite"
        if client is None:
            client = client_gemini_paid
            model  = "gemini-2.0-flash-lite"

        resp = client.models.generate_content(
            model=model,
            contents=gemini_history,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1200,
                temperature=0.85,
            )
        )
        full_text = resp.text or ""

        if wants_inject and "<<<INJECT_TEXT>>>" in full_text:
            parts      = full_text.split("<<<INJECT_TEXT>>>")
            response   = parts[0].strip()
            inject_raw = parts[1].split("<<<END_INJECT>>>")[0].strip() if len(parts) > 1 else ""
            return jsonify({"response": response or "Voici le passage.", "inject": True, "inject_text": inject_raw, "action": None})

        return jsonify({"response": full_text, "inject": False, "action": None})

    except Exception as e:
        print(f"Erreur /books: {e}")
        return jsonify({"response": "Studio instable, reessaie !", "inject": False, "action": None}), 500

# ── ROUTE /home ───────────────────────────────────────────────────────────────
@app.route("/home", methods=["POST"])
def home():
    try:
        data = request.json or {}
        ctx = prepare_shared_context(data, source_override="home")

        if ctx["user_tier"] == "connected_free":
            if get_failover_count() >= MAX_FREE_FAILOVERS:
                return jsonify({"action": None, "response": "Sillage d'accueil au repos ! 😎"})

            model_1 = "deepseek/DeepSeek-V3-0324"
            if client_github and not is_model_locked(model_1):
                try:
                    res = execute_openai_call(client_github, model_1, ctx)
                    return jsonify(clean_and_parse_json(res))
                except Exception as e:
                    print(f"Echec {model_1} ({e})")
                    lock_model(model_1)

            model_2 = "moonshotai/kimi-k2.6"
            if client_nvidia and not is_model_locked(model_2):
                try:
                    res = execute_openai_call(client_nvidia, model_2, ctx)
                    return jsonify(clean_and_parse_json(res))
                except Exception as e:
                    print(f"Echec {model_2} ({e})")
                    lock_model(model_2)

            if client_gemini_paid and not is_model_locked("gemini-2.5-flash-lite-home"):
                try:
                    r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                    increment_failover_count()
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec filet home ({e})")
                    lock_model("gemini-2.5-flash-lite-home")

            return jsonify({"action": None, "response": "Accueil surcharge, reessaie ! 😎"})

        else:
            try:
                r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                return jsonify(clean_and_parse_json(r.text))
            except Exception as e:
                print(f"Echec home paid ({e})")
                return jsonify({"action": None, "response": "Accueil instable, reessaie !"}), 500

    except Exception as e:
        print(f"Erreur /home: {e}")
        return jsonify({"action": None, "response": "Accueil instable !"}), 500

# ── ROUTE /history ────────────────────────────────────────────────────────────
@app.route("/history", methods=["POST"])
def history():
    try:
        data = request.json or {}
        ctx = prepare_shared_context(data, source_override="history")

        if ctx["user_tier"] == "connected_free":
            if get_failover_count() >= MAX_FREE_FAILOVERS:
                return jsonify({"action": None, "response": "Archives inaccessibles ! 😎"})

            model_1 = "groq/compound"
            if client_groq and not is_model_locked(model_1):
                try:
                    res = execute_openai_call(client_groq, model_1, ctx)
                    return jsonify(clean_and_parse_json(res))
                except Exception as e:
                    print(f"Echec {model_1} ({e})")
                    lock_model(model_1)

            model_2 = "moonshotai/kimi-k2.6"
            if client_nvidia and not is_model_locked(model_2):
                try:
                    res = execute_openai_call(client_nvidia, model_2, ctx)
                    return jsonify(clean_and_parse_json(res))
                except Exception as e:
                    print(f"Echec {model_2} ({e})")
                    lock_model(model_2)

            if client_gemini_paid and not is_model_locked("gemini-2.5-flash-lite-history"):
                try:
                    r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                    increment_failover_count()
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec filet history ({e})")
                    lock_model("gemini-2.5-flash-lite-history")

            return jsonify({"action": None, "response": "Historique sature, reessaie ! 😎"})

        else:
            try:
                r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                return jsonify(clean_and_parse_json(r.text))
            except Exception as e:
                print(f"Echec history paid ({e})")
                return jsonify({"action": None, "response": "Historique instable !"}), 500

    except Exception as e:
        print(f"Erreur /history: {e}")
        return jsonify({"action": None, "response": "Historique instable !"}), 500

# ── ROUTE /horizon ────────────────────────────────────────────────────────────
def extract_horizon_result(query, ctx, attempt=1, max_attempts=3):
    if attempt > max_attempts:
        return {
            "response": "Le signal web est trop fragmenté pour être validé après plusieurs tentatives.",
            "attributes": ["erreur_coherence"],
            "matrix": {
                "c_est_quoi": "Erreur d'extraction structurelle.",
                "est_ce_bon": "Signal trop fragmenté.",
                "combien_ca_coute": "Non disponible.",
                "est_ce_disponible": "Non disponible.",
                "qu_en_pensent_les_gens": "Données incohérentes.",
                "quelles_sont_les_alternatives": "Non disponible.",
                "quels_sont_les_risques": "Instabilité du flux détectée.",
                "quelle_option_est_recommandee": "Echo a interrompu la boucle pour cause d'incohérence persistante."
            }
        }

    try:
        if ctx["user_tier"] == "connected_free":
            client = client_gemini_free if client_gemini_free else client_gemini_paid
            model  = "gemini-2.5-flash-lite"
        elif ctx["user_tier"] == "founder":
            client = client_gemini_paid
            model  = "gemini-2.0-flash"
        else:
            client = client_gemini_paid
            model  = "gemini-2.5-flash-lite"

        r = execute_gemini_call(client, model, ctx)
        parsed = clean_and_parse_horizon_json(r.text)

        required_matrix_keys = [
            "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible",
            "qu_en_pensent_les_gens", "quelles_sont_les_alternatives",
            "quels_sont_les_risques", "quelle_option_est_recommandee"
        ]

        has_response   = "response" in parsed and parsed["response"]
        has_attributes = "attributes" in parsed and isinstance(parsed["attributes"], list)
        has_matrix     = "matrix" in parsed and isinstance(parsed["matrix"], dict) and all(
            k in parsed["matrix"] for k in required_matrix_keys
        )

        if not has_response or not has_attributes or not has_matrix:
            print(f"[HORIZON AGENT] Tentative {attempt} - structure incomplete. Relancement...")
            return extract_horizon_result(query, ctx, attempt + 1, max_attempts)

        return parsed

    except Exception as e:
        print(f"[HORIZON AGENT] Erreur tentative {attempt}: {e}")
        return extract_horizon_result(query, ctx, attempt + 1, max_attempts)


@app.route("/horizon", methods=["POST"])
def horizon():
    try:
        data  = request.json or {}
        query = data.get("query", "").strip()

        if not query:
            return jsonify({"error": "L'intention d'exploration est vide."}), 400

        data["message"] = (
            f"Fais une recherche web complete et extrait tout sur : {query}. "
            f"Reponds OBLIGATOIREMENT en JSON valide avec les cles : response, attributes, matrix."
        )

        ctx = prepare_shared_context(data, source_override="horizonweb")

        if ctx["user_tier"] == "connected_free":
            if get_failover_count() >= MAX_FREE_FAILOVERS:
                return jsonify({
                    "response": "Ouf, mon sillage Horizon sature ! 😎",
                    "attributes": ["quota_atteint"],
                    "matrix": None
                })

        result = extract_horizon_result(query, ctx)
        return jsonify(result)

    except Exception as e:
        print(f"Erreur critique /horizon: {e}")
        return jsonify({
            "response": "Systeme Horizon instable, l'axe n'a pas pu se stabiliser.",
            "attributes": ["erreur_critique"],
            "matrix": None
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Echo API sur le port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)