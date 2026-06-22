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
client_groq         = OpenAI(base_url=GROQ_BASE_URL,        api_key=GROQ_API_KEY)        if GROQ_API_KEY       else None
client_cloudflare   = OpenAI(base_url=CLOUDFLARE_BASE_URL, api_key=CLOUDFLARE_API_TOKEN) if CLOUDFLARE_API_TOKEN else None

GLOBAL_FAILOVER_MEMORY_COUNT = 0
MAX_FREE_FAILOVERS = 200

def get_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    return GLOBAL_FAILOVER_MEMORY_COUNT

def increment_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    GLOBAL_FAILOVER_MEMORY_COUNT += 1
    print(f"[FAILOVER FILET] {GLOBAL_FAILOVER_MEMORY_COUNT} / {MAX_FREE_FAILOVERS}")

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

def clean_and_parse_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"):   text = text[3:]
    if text.endswith("```"):       text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except Exception: pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception: pass

    raise ValueError("Format JSON invalide ou absent.")

def build_gemini_contents(historique_reduit, image_b64, user_message, force_neutral_style):
    contents = []
    for msg in historique_reduit:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"): continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or clean_content == "...": continue
        if msg.startswith("You:") or msg.startswith("Toi:"):
            contents.append({"role": "user", "parts": [types.Part.from_text(text=clean_content)]})
        elif msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception: pass
            if force_neutral_style: clean_content = "[Analyse technique archivee]"
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
    lang             = data.get("lang", "fr").strip().lower()

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

    system_prompt = generate_system_prompt(
        source=source, selected_buttons=selected_buttons, date_aujourdhui=date_aujourdhui,
        annee_en_cours=annee_en_cours, user_tier=user_tier, filtered_calendar=filtered_calendar,
        current_expenses=current_expenses, current_calories=current_calories, current_cycle=current_cycle,
        lang=lang
    )

    taille_memoire = 30 if user_tier in ["ultra", "founder"] else (15 if user_tier in ["basic", "premium"] else 5)
    output_tokens  = 4096 if user_tier in ["ultra", "founder"] else (2048 if user_tier in ["basic", "premium"] else 1024)
    historique_ajuste = raw_history[-taille_memoire:]
    force_neutral = source == "vitality"
    gemini_contents = build_gemini_contents(historique_ajuste, image_b64, user_message, force_neutral)

    messages_openrouter = [{"role": "system", "content": system_prompt}]
    for msg in historique_ajuste:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"): continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or clean_content == "...": continue
        if msg.startswith("You:") or msg.startswith("Toi:"):
            messages_openrouter.append({"role": "user", "content": clean_content})
        elif msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception: pass
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

def execute_gemini_call(client, model, ctx):
    return client.models.generate_content(
        model=model, contents=ctx["gemini_contents"],
        config=types.GenerateContentConfig(
            system_instruction=ctx["system_prompt"],
            max_output_tokens=ctx["output_tokens"]
        )
    )

def execute_openai_call(client, model, ctx, temp=0.7, timeout=7.0):
    res = client.chat.completions.create(
        model=model, messages=ctx["messages_openrouter"],
        temperature=temp, timeout=timeout
    )
    return res.choices[0].message.content

def extract_attributes_and_matrix(query, ctx, lang_target="fr", attempt=1, max_attempts=3):
    if attempt > max_attempts:
        fallback_msg = (
            "Erreur d'extraction du sillage de recherche." if lang_target == "fr"
            else "Search wake extraction error."
        )
        return {
            "response": fallback_msg,
            "attributes": ["erreur_coherence"],
            "matrix": {
                "c_est_quoi": "Erreur d'extraction structurelle.",
                "est_ce_bon": "Le signal web est trop fragmenté pour être validé.",
                "combien_ca_coute": "Non disponible.",
                "est_ce_disponible": "Non disponible.",
                "qu_en_pensent_les_gens": "Données incohérentes.",
                "quelles_sont_les_alternatives": "Non disponible.",
                "quels_sont_les_risques": "Instabilité détectée.",
                "quelle_option_est_recommandee": "Incohérence persitante."
            }
        }

    try:
        if ctx["user_tier"] == "connected_free":
            model = "gemini-3.1-flash-lite"
            client = client_gemini_free if client_gemini_free else client_gemini_paid
        else:
            model = "gemini-3.5-flash" if ctx["user_tier"] == "founder" else "gemini-3.1-flash-lite"
            client = client_gemini_paid

        if client:
            try:
                r = execute_gemini_call(client, model, ctx)
                parsed_json = clean_and_parse_json(r.text)
                return validate_and_format_horizon(parsed_json, query, ctx, lang_target, attempt, max_attempts)
            except Exception as e:
                print(f"[HORIZON WEB] Echec Gemini ({e}). Cascade vers GitHub...")

        if client_github:
            try:
                res_raw = execute_openai_call(client_github, "deepseek/DeepSeek-V3-0324", ctx)
                parsed_json = clean_and_parse_json(res_raw)
                return validate_and_format_horizon(parsed_json, query, ctx, lang_target, attempt, max_attempts)
            except Exception as e:
                print(f"[HORIZON WEB] Echec DeepSeek ({e}). Cascade vers Nvidia...")

        if client_nvidia:
            try:
                res_raw = execute_openai_call(client_nvidia, "moonshotai/kimi-k2.6", ctx)
                parsed_json = clean_and_parse_json(res_raw)
                return validate_and_format_horizon(parsed_json, query, ctx, lang_target, attempt, max_attempts)
            except Exception as e:
                print(f"[HORIZON WEB] Echec Moonshot ({e}).")

        raise ValueError("Aucune IA n'a pu extraire de matrice valide.")

    except Exception as e:
        print(f"[HORIZON AGENT] Erreur crash a la tentative {attempt}: {e}")
        return extract_attributes_and_matrix(query, ctx, lang_target, attempt + 1, max_attempts)

def validate_and_format_horizon(parsed_json, query, ctx, lang_target, attempt, max_attempts):
    if not isinstance(parsed_json, dict) or "matrix" not in parsed_json or "response" not in parsed_json:
        print(f"[HORIZON AGENT] Tentative {attempt} echouee (Structure de base manquante).")
        return extract_attributes_and_matrix(query, ctx, lang_target, attempt + 1, max_attempts)

    required_keys = [
        "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible",
        "qu_en_pensent_les_gens", "quelles_sont_les_alternatives",
        "quels_sont_les_risques", "quelle_option_est_recommandee"
    ]
    if not all(k in parsed_json["matrix"] for k in required_keys):
        print(f"[HORIZON AGENT] Tentative {attempt} echouee (Cles de matrice absentes).")
        return extract_attributes_and_matrix(query, ctx, lang_target, attempt + 1, max_attempts)

    return parsed_json

@app.route("/horizon", methods=["POST"])
def horizon():
    try:
        data = request.json or {}
        query = data.get("query", "").strip()
        lang_target = data.get("lang", "fr").strip().lower()

        if not query:
            return jsonify({"error": "L'intention d'exploration est vide."}), 400

        data["message"] = f"Fais une recherche web complete sur : {query}"
        ctx = prepare_shared_context(data, source_override="horizonweb")

        result = extract_attributes_and_matrix(query, ctx, lang_target=lang_target)
        return jsonify(result)

    except Exception as e:
        print(f"Erreur critique sur la route /horizon: {e}")
        return jsonify({
            "response": "Le systeme de recherche a rencontre une erreur.",
            "matrix": {"quelle_option_est_recommandee": "Systeme Horizon instable."},
            "attributes": ["erreur_critique"]
        }), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json or {}
        ctx = prepare_shared_context(data, source_override="chat")

        if ctx["user_tier"] == "connected_free":
            current_failovers = get_failover_count()
            if current_failovers >= MAX_FREE_FAILOVERS:
                return jsonify({"action": None, "response": "Ouf, mon sillage sature ! 😎"})

            model_1 = "gemini-3.1-flash-lite"
            if client_gemini_free and not is_model_locked(model_1):
                try:
                    r = execute_gemini_call(client_gemini_free, model_1, ctx)
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec {model_1} ({e})"); lock_model(model_1)

            model_2 = "gemini-2.5-flash-lite"
            if client_gemini_free and not is_model_locked(model_2):
                try:
                    r = execute_gemini_call(client_gemini_free, model_2, ctx)
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec {model_2} ({e})"); lock_model(model_2)

            if client_gemini_paid and not is_model_locked("gemini-2.5-flash-lite-paid"):
                try:
                    r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                    increment_failover_count()
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec filet ({e})"); lock_model("gemini-2.5-flash-lite-paid")

            return jsonify({"action": None, "response": "Sillage sature, reessaie ! 😎"})

        else:
            target = "gemini-3.5-flash" if ctx["user_tier"] == "founder" else "gemini-3.1-flash-lite"
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
            if msg.startswith("You: ") or msg.startswith("Toi: "):
                gemini_history.append(types.Content(role="user",  parts=[types.Part.from_text(text=msg[5:])]))
            elif msg.startswith("Echo: "):
                gemini_history.append(types.Content(role="model", parts=[types.Part.from_text(text=msg[6:])]))
        gemini_history.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))

        client = client_gemini_paid if tier in ("premium", "ultra", "founder") else client_gemini_free
        model  = "gemini-2.0-flash" if tier in ("premium", "ultra", "founder") else "gemini-2.0-flash-lite"
        if client is None:
            client = client_gemini_paid
            model  = "gemini-2.0-flash-lite"

        if client:
            try:
                resp = client.models.generate_content(
                    model=model, contents=gemini_history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=1200,
                        temperature=0.85,
                    )
                )
                full_text = resp.text or ""
                return handle_books_response(full_text, wants_inject)
            except Exception as e:
                print(f"[BOOKS CASCADE] Echec Gemini ({e}). Cascade vers GitHub...")

        if client_github:
            try:
                ctx_dummy = {"messages_openrouter": [{"role": "system", "content": system_prompt}] + [{"role": "user", "content": message}]}
                res_raw = execute_openai_call(client_github, "deepseek/DeepSeek-V3-0324", ctx_dummy)
                return handle_books_response(res_raw, wants_inject)
            except Exception as e:
                print(f"[BOOKS CASCADE] Echec DeepSeek ({e}). Cascade vers Nvidia...")

        return jsonify({"response": "Studio d'ecriture instable.", "inject": False, "action": None}), 500

    except Exception as e:
        print(f"Erreur /books: {e}")
        return jsonify({"response": "Studio instable, reessaie !", "inject": False, "action": None}), 500

def handle_books_response(full_text, wants_inject):
    if wants_inject and "<<<INJECT_TEXT>>>" in full_text:
        parts = full_text.split("<<<INJECT_TEXT>>>")
        response = parts[0].strip()
        inject_raw = parts[1].split("<<<END_INJECT>>>")[0].strip() if len(parts) > 1 else ""
        return jsonify({"response": response or "Voici le passage.", "inject": True, "inject_text": inject_raw, "action": None})

    return jsonify({"response": full_text, "inject": False, "action": None})

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
                    print(f"Echec {model_1} ({e})"); lock_model(model_1)

            model_2 = "moonshotai/kimi-k2.6"
            if client_nvidia and not is_model_locked(model_2):
                try:
                    res = execute_openai_call(client_nvidia, model_2, ctx)
                    return jsonify(clean_and_parse_json(res))
                except Exception as e:
                    print(f"Echec {model_2} ({e})"); lock_model(model_2)

            if client_gemini_paid and not is_model_locked("gemini-2.5-flash-lite-home"):
                try:
                    r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                    increment_failover_count()
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec filet home ({e})"); lock_model("gemini-2.5-flash-lite-home")

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
                    print(f"Echec {model_1} ({e})"); lock_model(model_1)

            model_2 = "moonshotai/kimi-k2.6"
            if client_nvidia and not is_model_locked(model_2):
                try:
                    res = execute_openai_call(client_nvidia, model_2, ctx)
                    return jsonify(clean_and_parse_json(res))
                except Exception as e:
                    print(f"Echec {model_2} ({e})"); lock_model(model_2)

            if client_gemini_paid and not is_model_locked("gemini-2.5-flash-lite-history"):
                try:
                    r = execute_gemini_call(client_gemini_paid, "gemini-2.5-flash-lite", ctx)
                    increment_failover_count()
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as e:
                    print(f"Echec filet history ({e})"); lock_model("gemini-2.5-flash-lite-history")

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Echo API sur le port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)