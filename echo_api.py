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

# ── MODÈLES ────────────────────────────────────────────────────────────────────
MODELS = {
    # Gemini (clé propre)
    "gemini_paid_founder":  "gemini-3.5-flash",
    "gemini_paid_ultra":    "gemini-3.1-flash-lite",
    "gemini_paid_standard": "gemini-2.5-flash-lite",
    # OpenRouter payant
    "mistral":    "mistralai/mistral-small-24b-instruct-2501",
    "hy3":        "tencent/hy3-preview",
    "owl":        "openrouter/owl-alpha",
    "llama":      "meta-llama/llama-3.3-70b-instruct",
    # DeepSeek direct
    "deepseek":   "deepseek-chat",
}

FREE_MAX_TOKENS = 2_500
PAID_MAX_TOKENS = 5_000

# ── CLÉS & CLIENTS ─────────────────────────────────────────────────────────────
API_KEY_PAID          = os.getenv("API_KEY_PAID", "").strip()
OPENROUTER_API_KEY    = os.getenv("OPENROUTER_API_KEY", "").strip()
DEEPSEEK_API_KEY      = os.getenv("DEEPSEEK_API_KEY", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()

client_gemini_paid = genai.Client(api_key=API_KEY_PAID) if API_KEY_PAID else None

import httpx
_shared_http_client = httpx.Client(timeout=35.0)

client_openrouter = (
    OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY, http_client=_shared_http_client)
    if OPENROUTER_API_KEY else None
)

client_deepseek = (
    OpenAI(base_url="https://api.deepseek.com", api_key=DEEPSEEK_API_KEY, http_client=_shared_http_client)
    if DEEPSEEK_API_KEY else None
)

_cf_session = _requests_lib.Session()

# ── FAILOVER GLOBAL ────────────────────────────────────────────────────────────
GLOBAL_FAILOVER_MEMORY_COUNT = 0
MAX_FREE_FAILOVERS = 200

def get_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    return GLOBAL_FAILOVER_MEMORY_COUNT

def increment_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    GLOBAL_FAILOVER_MEMORY_COUNT += 1
    print(f"[FAILOVER] {GLOBAL_FAILOVER_MEMORY_COUNT} / {MAX_FREE_FAILOVERS}")

# ── LOCK MODÈLES — 30s ─────────────────────────────────────────────────────────
MODELS_LOCK_REGISTRY = {}
_lock_mutex = threading.Lock()

def is_model_locked(model_key: str) -> bool:
    with _lock_mutex:
        lock_time = MODELS_LOCK_REGISTRY.get(model_key)
        if lock_time:
            if datetime.now() < lock_time:
                return True
            else:
                del MODELS_LOCK_REGISTRY[model_key]
        return False

def lock_model(model_key: str, seconds: int = 30):
    with _lock_mutex:
        MODELS_LOCK_REGISTRY[model_key] = datetime.now() + timedelta(seconds=seconds)
    print(f"[LOCK] {model_key} hors circuit {seconds}s.")

# ── TIERS ──────────────────────────────────────────────────────────────────────
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

def is_paid_tier(tier: str) -> bool:
    return tier in ("basic", "premium", "ultra", "founder")

# ── ERREURS STANDARD ───────────────────────────────────────────────────────────
ERR_QUOTA   = {"action": None, "response": "Le service est temporairement sature. Reessaie dans quelques instants."}
ERR_FINAL   = {"action": None, "response": "Tous les serveurs sont momentanement indisponibles. Reessaie dans 1 minute."}
ERR_CRASH   = {"action": None, "response": "Une erreur inattendue s'est produite. Reessaie dans quelques secondes."}
ERR_HORIZON = {"response": "Le moteur de recherche est temporairement indisponible.", "attributes": [], "matrix": None}

# ── PARSERS JSON ───────────────────────────────────────────────────────────────
def clean_and_parse_json(raw_text):
    if not raw_text or not isinstance(raw_text, str):
        raise ValueError("Reponse vide ou invalide.")
    text = raw_text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"):   text = text[3:]
    if text.endswith("```"):       text = text[:-3]
    text = text.strip()
    if not text:
        raise ValueError("Reponse vide apres nettoyage.")
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
    if '"response":' in text:
        res_match = re.search(r'"response"\s*:\s*"([^"]+)"', text)
        if res_match:
            return {"action": None, "response": res_match.group(1)}
    return {"action": None, "response": text}

def clean_and_parse_horizon_json(raw_text):
    if not raw_text or not isinstance(raw_text, str):
        return {"response": "", "attributes": [], "matrix": None}
    text = raw_text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"):   text = text[3:]
    if text.endswith("```"):       text = text[:-3]
    text = text.strip()
    if not text:
        return {"response": "", "attributes": [], "matrix": None}
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
    resp_match = re.search(r'"response"\s*:\s*"(.*?)"(?:\s*,|\s*\})', text, re.DOTALL)
    if resp_match:
        return {"response": resp_match.group(1).replace('\\n', '\n').replace('\\"', '"'), "attributes": [], "matrix": None}
    return {"response": text.replace("**", "").replace("##", "").replace("# ", ""), "attributes": [], "matrix": None}

# ── BUILD CONTENTS ─────────────────────────────────────────────────────────────
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

# ── CONTEXTE PARTAGÉ ───────────────────────────────────────────────────────────
def prepare_shared_context(data, source_override=None):
    user_message     = data.get("message", "")
    calendar_events  = data.get("calendarEvents", {})
    raw_history      = data.get("history", [])
    memory_summary   = data.get("summary", "")
    source           = source_override or (data.get("source") or "chat").lower().strip()
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
        current_cycle=current_cycle,
    )

    system_prompt = base_system_prompt
    if memory_summary and user_tier not in ("connected_free", "basic"):
        system_prompt += f"\n\nLONG TERM MEMORY\n================\n{memory_summary}\n"
    system_prompt += "\n\nCRITICAL SAFETY DIRECTIVE: Only trigger actions explicitly demanded in the LATEST message."

    taille_memoire  = 30 if user_tier in ("ultra", "founder") else (15 if user_tier in ("basic", "premium") else 5)
    output_tokens   = PAID_MAX_TOKENS if is_paid_tier(user_tier) else FREE_MAX_TOKENS
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
            messages_openai.append({"role": "user", "content": re.sub(r'\s{3,}', ' ', clean_content).strip()})
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

# ── CALL HELPERS ───────────────────────────────────────────────────────────────
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

def call_gemini(client, model_key, ctx, timeout=25, temperature=0.5):
    def fn():
        return client.models.generate_content(
            model=MODELS[model_key],
            contents=ctx["gemini_contents"],
            config=types.GenerateContentConfig(
                system_instruction=ctx["system_prompt"],
                max_output_tokens=ctx["output_tokens"],
                temperature=temperature,
            )
        )
    return call_with_timeout(fn, timeout)

def call_gemini_with_search(client, model_key, ctx, timeout=30, temperature=0.5):
    def fn():
        return client.models.generate_content(
            model=MODELS[model_key],
            contents=ctx["gemini_contents"],
            config=types.GenerateContentConfig(
                system_instruction=ctx["system_prompt"],
                max_output_tokens=ctx["output_tokens"],
                temperature=temperature,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
        )
    return call_with_timeout(fn, timeout)

def call_openrouter(model_key, ctx, temp=0.5, timeout=20.0):
    """Appel OpenRouter — mistral, hy3, owl, llama passent par ici."""
    if client_openrouter is None:
        raise RuntimeError("OpenRouter non configuré")
    res = client_openrouter.chat.completions.create(
        model=MODELS[model_key],
        messages=ctx["messages_openai"],
        temperature=temp,
        max_tokens=ctx.get("output_tokens", FREE_MAX_TOKENS),
        timeout=timeout,
    )
    content = res.choices[0].message.content
    if content is None:
        raise ValueError(f"Reponse vide de {model_key}")
    return content

def call_deepseek(ctx, temp=0.5, timeout=20.0):
    """Appel DeepSeek direct via leur API OpenAI-compatible."""
    if client_deepseek is None:
        raise RuntimeError("DeepSeek non configuré")
    res = client_deepseek.chat.completions.create(
        model=MODELS["deepseek"],
        messages=ctx["messages_openai"],
        temperature=temp,
        max_tokens=ctx.get("output_tokens", FREE_MAX_TOKENS),
        timeout=timeout,
    )
    content = res.choices[0].message.content
    if content is None:
        raise ValueError("Reponse vide de deepseek")
    return content

# ── CASCADE PAYANTE par tier ───────────────────────────────────────────────────
def run_paid_cascade(ctx, page_timeout: int = 10):
    """
    page_timeout : timeout par modèle (varie selon la page)
    basic    → mistral → hy3 → gemini_paid_standard
    premium  → deepseek direct → mistral → gemini_paid_standard
    ultra    → deepseek direct → llama → gemini_paid_standard
    founder  → gemini_paid_founder → deepseek direct → gemini_paid_standard
    """
    tier = ctx["user_tier"]
    t    = page_timeout

    if tier == "basic":
        steps = [
            ("or", "mistral",              t),
            ("or", "hy3",                  t),
            ("g",  "gemini_paid_standard", 15),
        ]
    elif tier == "premium":
        steps = [
            ("ds", "deepseek",             t),
            ("or", "mistral",              t),
            ("g",  "gemini_paid_standard", 15),
        ]
    elif tier == "ultra":
        steps = [
            ("ds", "deepseek",             t),
            ("or", "llama",                t),
            ("g",  "gemini_paid_standard", 15),
        ]
    else:  # founder
        steps = [
            ("g",  "gemini_paid_founder",  t),
            ("ds", "deepseek",             t),
            ("g",  "gemini_paid_standard", 15),
        ]

    for provider, model_key, timeout in steps:
        if is_model_locked(model_key):
            continue
        try:
            if provider == "g":
                r      = call_gemini(client_gemini_paid, model_key, ctx, timeout=timeout, temperature=0.5)
                result = clean_and_parse_json(r.text)
            elif provider == "ds":
                r      = call_deepseek(ctx, temp=0.5, timeout=float(timeout))
                result = clean_and_parse_json(r)
            else:
                r      = call_openrouter(model_key, ctx, temp=0.5, timeout=float(timeout))
                result = clean_and_parse_json(r)
            return result
        except Exception as e:
            print(f"[PAID {tier}] Echec {model_key} ({e})")
            lock_model(model_key, 30)

    return ERR_FINAL

# ── CASCADE FREE ───────────────────────────────────────────────────────────────
def run_free_cascade(steps, ctx, parser=None, is_horizon=False):
    """
    steps : liste de (provider, model_key, timeout)
            provider = "g" (Gemini) | "or" (OpenRouter) | "gs" (Gemini+Search) | "ds" (DeepSeek direct)
    is_horizon : désactive le compteur failover global
    """
    if parser is None:
        parser = clean_and_parse_json
    if not is_horizon and get_failover_count() >= MAX_FREE_FAILOVERS:
        return ERR_QUOTA

    for i, (provider, model_key, timeout) in enumerate(steps):
        if provider in ("or",) and client_openrouter is None:
            continue
        if provider == "ds" and client_deepseek is None:
            continue
        if is_model_locked(model_key):
            continue
        is_last = (i == len(steps) - 1)
        try:
            if provider == "g":
                r      = call_gemini(client_gemini_paid, model_key, ctx, timeout=timeout, temperature=0.5)
                result = parser(r.text)
            elif provider == "gs":
                r      = call_gemini_with_search(client_gemini_paid, model_key, ctx, timeout=timeout, temperature=0.5)
                result = parser(r.text)
            elif provider == "ds":
                r      = call_deepseek(ctx, temp=0.5, timeout=float(timeout))
                result = parser(r)
            else:  # "or"
                r      = call_openrouter(model_key, ctx, temp=0.5, timeout=float(timeout))
                result = parser(r)

            if is_last and not is_horizon:
                increment_failover_count()
            return result
        except Exception as e:
            print(f"[FREE] Echec {model_key} ({e})")
            lock_model(model_key, 30)

    return ERR_FINAL

# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.route("/ping")
def ping():
    return jsonify({"status": "awake"})

# ── /home ──────────────────────────────────────────────────────────────────────
@app.route("/home", methods=["POST"])
def home():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="home")
        if is_paid_tier(ctx["user_tier"]):
            return jsonify(run_paid_cascade(ctx, page_timeout=10))
        steps = [
            ("or", "mistral",              8),
            ("or", "hy3",                 12),
            ("g",  "gemini_paid_standard", 15),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /home: {e}")
        return jsonify(ERR_CRASH), 500

# ── /chat ──────────────────────────────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="chat")
        if is_paid_tier(ctx["user_tier"]):
            return jsonify(run_paid_cascade(ctx, page_timeout=10))
        steps = [
            ("or", "mistral",              8),
            ("or", "hy3",                 12),
            ("g",  "gemini_paid_standard", 15),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /chat: {e}")
        return jsonify(ERR_CRASH), 500

# ── /vitality ─────────────────────────────────────────────────────────────────
@app.route("/vitality", methods=["POST"])
def vitality():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="vitality")
        if is_paid_tier(ctx["user_tier"]):
            return jsonify(run_paid_cascade(ctx, page_timeout=20))
        steps = [
            ("or", "hy3",                 20),
            ("or", "mistral",             20),
            ("g",  "gemini_paid_standard", 15),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /vitality: {e}")
        return jsonify(ERR_CRASH), 500

# ── /history ──────────────────────────────────────────────────────────────────
@app.route("/history", methods=["POST"])
def history():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="history")
        if is_paid_tier(ctx["user_tier"]):
            return jsonify(run_paid_cascade(ctx, page_timeout=12))

        if get_failover_count() >= MAX_FREE_FAILOVERS:
            return jsonify(ERR_QUOTA)

        result = None

        # ── owl-alpha : lock 60s après TOUTE réponse (succès ou échec) ──
        if not is_model_locked("owl"):
            try:
                r      = call_openrouter("owl", ctx, temp=0.5, timeout=15.0)
                result = clean_and_parse_json(r)
                print("[HISTORY] owl-alpha OK")
            except Exception as e:
                print(f"[HISTORY] owl-alpha echec ({e})")
            finally:
                lock_model("owl", 60)  # toujours locker owl après passage

        # Fallback si owl a échoué ou était locked
        if result is None:
            fallback_steps = [
                ("or", "mistral",              20),
                ("g",  "gemini_paid_standard", 20),
            ]
            result = run_free_cascade(fallback_steps, ctx)

        return jsonify(result)
    except Exception as e:
        print(f"Erreur /history: {e}")
        return jsonify(ERR_CRASH), 500

# ── /books ────────────────────────────────────────────────────────────────────
@app.route("/books", methods=["POST"])
def books():
    try:
        data       = request.json or {}
        message    = (data.get("message") or "").strip()
        history    = data.get("history", [])
        tier       = normalize_tier(data.get("userTier", "connected_free"))
        buttons    = data.get("selectedButtons", [])
        book_title = (data.get("bookTitle") or "").strip()
        output_tokens = 2048 if is_paid_tier(tier) else 1024

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

        # Historique Gemini avec alternance stricte
        gemini_history = []
        for msg in history[-10:]:
            if msg.startswith("You: "):
                gemini_history.append(types.Content(role="user",  parts=[types.Part.from_text(text=msg[5:])]))
            elif msg.startswith("Echo: "):
                if gemini_history:
                    gemini_history.append(types.Content(role="model", parts=[types.Part.from_text(text=msg[6:])]))
        gemini_history.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))

        def run_books_call_gemini(model_key, timeout):
            def fn():
                return client_gemini_paid.models.generate_content(
                    model=MODELS[model_key],
                    contents=gemini_history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=output_tokens,
                        temperature=0.5,
                    )
                )
            resp = call_with_timeout(fn, timeout)
            if not resp or not resp.text:
                raise ValueError("Reponse Gemini vide")
            return resp.text

        def run_books_call_openrouter(model_key, timeout):
            openai_messages = [{"role": "system", "content": system_prompt}]
            for msg in history[-10:]:
                if msg.startswith("You: "):
                    openai_messages.append({"role": "user",      "content": msg[5:]})
                elif msg.startswith("Echo: "):
                    openai_messages.append({"role": "assistant", "content": msg[6:]})
            openai_messages.append({"role": "user", "content": message})
            res = client_openrouter.chat.completions.create(
                model=MODELS[model_key],
                messages=openai_messages,
                temperature=0.5,
                max_tokens=output_tokens,
                timeout=float(timeout),
            )
            content = res.choices[0].message.content
            if not content:
                raise ValueError(f"Reponse vide de {model_key}")
            return content

        def run_books_call_deepseek(timeout):
            openai_messages = [{"role": "system", "content": system_prompt}]
            for msg in history[-10:]:
                if msg.startswith("You: "):
                    openai_messages.append({"role": "user",      "content": msg[5:]})
                elif msg.startswith("Echo: "):
                    openai_messages.append({"role": "assistant", "content": msg[6:]})
            openai_messages.append({"role": "user", "content": message})
            res = client_deepseek.chat.completions.create(
                model=MODELS["deepseek"],
                messages=openai_messages,
                temperature=0.5,
                max_tokens=output_tokens,
                timeout=float(timeout),
            )
            content = res.choices[0].message.content
            if not content:
                raise ValueError("Reponse vide de deepseek")
            return content

        # Cascade books
        books_steps = [
            ("g",  "gemini_paid_standard", 20),
            ("or", "hy3",                  25),
            ("or", "mistral",              20),
        ]
        if is_paid_tier(tier):
            t = 20
            if tier == "founder":
                books_steps = [
                    ("g",  "gemini_paid_founder", t),
                    ("ds", "deepseek",            t),
                    ("g",  "gemini_paid_standard", 15),
                ]
            elif tier == "ultra":
                books_steps = [
                    ("ds", "deepseek",             t),
                    ("or", "llama",                t),
                    ("g",  "gemini_paid_standard", 15),
                ]
            elif tier == "premium":
                books_steps = [
                    ("ds", "deepseek",             t),
                    ("or", "mistral",              t),
                    ("g",  "gemini_paid_standard", 15),
                ]
            else:  # basic
                books_steps = [
                    ("or", "mistral",              t),
                    ("or", "hy3",                  t),
                    ("g",  "gemini_paid_standard", 15),
                ]

        full_text = ""
        for i, (provider, model_key, timeout) in enumerate(books_steps):
            if is_model_locked(model_key):
                continue
            try:
                if provider == "g":
                    full_text = run_books_call_gemini(model_key, timeout)
                elif provider == "ds":
                    full_text = run_books_call_deepseek(timeout)
                else:
                    full_text = run_books_call_openrouter(model_key, timeout)
                if i == len(books_steps) - 1 and not is_paid_tier(tier):
                    increment_failover_count()
                break
            except Exception as e:
                print(f"[BOOKS] Echec {model_key} ({e})")
                lock_model(model_key, 30)

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

# ── /horizon ──────────────────────────────────────────────────────────────────
# Exception : mêmes modèles pour TOUS les tiers (free et payant)
@app.route("/horizon", methods=["POST"])
def horizon():
    try:
        data  = request.json or {}
        query = (data.get("query") or "").strip()
        if not query:
            return jsonify({"error": "L'intention d'exploration est vide."}), 400

        maintenant = datetime.now()
        date_str   = maintenant.strftime("%A %d %B %Y")
        heure_str  = maintenant.strftime("%H:%M")

        data["message"] = (
            f"DATE ET HEURE ACTUELLES : {date_str}, {heure_str} (heure locale du serveur).\n"
            f"ANNEE EN COURS : 2026. Toutes les informations doivent etre actuelles et valides en 2026.\n\n"
            f"INSTRUCTION OBLIGATOIRE — GOOGLE SEARCH ACTIVE :\n"
            f"Tu disposes d'un outil de recherche Google en temps reel. "
            f"Tu DOIS l'utiliser pour repondre a cette requete. "
            f"N'utilise PAS ta memoire interne comme source principale. "
            f"Cherche d'abord. Transmets ce que tu trouves. Rien d'autre.\n\n"
            f"REQUETE : {query}\n\n"
            f"REGLES DE TRANSMISSION :\n"
            f"- Retourne uniquement des informations confirmees par ta recherche Google.\n"
            f"- Si une donnee (adresse, telephone, horaire, prix, URL) est introuvable : utilise le jeton approprie.\n"
            f"- Retourne jusqu'a 10 resultats confirmes — moins si tu n'en trouves pas davantage.\n"
            f"- Une reponse incomplete est acceptable. Une reponse inventee est un echec.\n\n"
            f"Reponds UNIQUEMENT en JSON valide avec les cles : response, attributes, matrix."
        )

        ctx = prepare_shared_context(data, source_override="horizonweb")

        required_matrix_keys = [
            "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible",
            "qu_en_pensent_les_gens", "quelles_sont_les_alternatives",
            "quels_sont_les_risques", "quelle_option_est_recommandee"
        ]

        # Horizon : mêmes modèles pour tous les tiers
        # deepseek direct 25s → gemini-3.1-flash-lite+search 25s → llama (OR) 25s
        horizon_steps = [
            ("ds", "deepseek",        25),
            ("gs", "gemini_paid_ultra", 25),
            ("or", "llama",           25),
        ]

        parsed = None
        for provider, model_key, timeout in horizon_steps:
            if is_model_locked(model_key):
                continue
            try:
                print(f"[HORIZON] Tentative {model_key}")
                if provider == "gs":
                    r      = call_gemini_with_search(client_gemini_paid, model_key, ctx, timeout=timeout, temperature=0.5)
                    parsed = clean_and_parse_horizon_json(r.text)
                elif provider == "ds":
                    r      = call_deepseek(ctx, temp=0.5, timeout=float(timeout))
                    parsed = clean_and_parse_horizon_json(r)
                else:
                    r      = call_openrouter(model_key, ctx, temp=0.5, timeout=float(timeout))
                    parsed = clean_and_parse_horizon_json(r)

                if not parsed.get("response", "").strip():
                    print(f"[HORIZON] {model_key} reponse vide")
                    lock_model(model_key, 30)
                    continue

                if not isinstance(parsed.get("matrix"), dict) or not all(k in parsed["matrix"] for k in required_matrix_keys):
                    parsed["matrix"] = None
                if not isinstance(parsed.get("attributes"), list):
                    parsed["attributes"] = []

                print(f"[HORIZON] Succes — {model_key}")
                return jsonify(parsed)

            except Exception as e:
                print(f"[HORIZON] Echec {model_key} ({e})")
                lock_model(model_key, 30)

        return jsonify(ERR_HORIZON)

    except Exception as e:
        print(f"[HORIZON] Erreur critique: {e}")
        return jsonify(ERR_HORIZON), 500

# ── /memory-summary ───────────────────────────────────────────────────────────
@app.route("/memory-summary", methods=["POST"])
def memory_summary():
    try:
        data         = request.json or {}
        messages     = data.get("messages", [])
        prev_summary = data.get("summary", "")
        user_tier    = normalize_tier(data.get("userTier", "connected_free"))

        if not messages:
            return jsonify({"summary": prev_summary or ""})

        history_text = "\n".join(messages[-30:])
        prompt = (
            "Tu es un système de compression de mémoire conversationnelle.\n"
            "Ton rôle : produire un résumé dense et factuel de la conversation ci-dessous.\n"
            "Ce résumé sera injecté comme mémoire long terme dans les prochaines conversations.\n\n"
            f"RÉSUMÉ PRÉCÉDENT :\n{prev_summary or 'Aucun'}\n\n"
            f"NOUVEAUX MESSAGES :\n{history_text}\n\n"
            "INSTRUCTIONS :\n"
            "- Garde les faits importants, préférences, décisions, contexte clé.\n"
            "- Ignore les salutations et messages vides.\n"
            "- Sois concis : max 300 mots.\n"
            "- Réponds UNIQUEMENT avec le résumé, sans introduction ni explication."
        )

        ctx = {
            "system_prompt":   "Tu es un compresseur de mémoire conversationnelle. Réponds uniquement avec le résumé demandé.",
            "output_tokens":   600,
            "gemini_contents": [{"role": "user", "parts": [types.Part.from_text(text=prompt)]}],
            "messages_openai": [
                {"role": "system", "content": "Tu es un compresseur de mémoire conversationnelle."},
                {"role": "user",   "content": prompt},
            ],
            "user_tier": user_tier,
        }

        # Essai Gemini d'abord, fallback OpenRouter
        try:
            r       = call_gemini(client_gemini_paid, "gemini_paid_standard", ctx, timeout=20, temperature=0.1)
            summary = (r.text or "").strip() if r else ""
            if summary:
                return jsonify({"summary": summary})
        except Exception as e:
            print(f"[MEMORY] Gemini echec ({e}), fallback OpenRouter")

        try:
            r       = call_openrouter("mistral", ctx, temp=0.1, timeout=15.0)
            summary = r.strip() if r else ""
            if summary:
                return jsonify({"summary": summary})
        except Exception as e:
            print(f"[MEMORY] Echec total ({e})")

        return jsonify({"summary": prev_summary or ""})

    except Exception as e:
        print(f"[MEMORY] Erreur critique: {e}")
        return jsonify({"summary": ""}), 500

# ── /export ───────────────────────────────────────────────────────────────────
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
                styled = f'<html><head><meta charset="utf-8"><style>body{{font-family:sans-serif;font-size:11pt;line-height:1.6;color:#18181b}}h1{{font-size:22pt;border-bottom:1px solid #e4e4e7;padding-bottom:8px}}p{{margin-bottom:12px;text-align:justify}}</style></head><body><h1>{title}</h1>{html}</body></html>'
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
                t_para = doc.add_paragraph(); run = t_para.add_run(title)
                run.font.size = Pt(24); run.font.bold = True; run.font.color.rgb = RGBColor(15, 23, 42)
                clean = re.sub(r'<[^>]+>', '\n', html).replace('&nbsp;', ' ')
                for line in clean.split('\n'):
                    line = line.strip()
                    if line:
                        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                        p.add_run(line).font.size = Pt(11)
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

# ── WARMUP ────────────────────────────────────────────────────────────────────
def _warmup_api():
    try:
        print("[BOOST] Reveil des routes Echo...")
        _requests_lib.get("http://127.0.0.1:5000/ping", timeout=2)
    except Exception:
        pass

threading.Thread(target=_warmup_api, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)