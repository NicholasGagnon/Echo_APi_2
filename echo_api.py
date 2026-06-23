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
    "gemini_free_1":        "gemini-3.1-flash-lite",
    "gemini_free_2":        "gemini-2.5-flash-lite",
    "deepseek":             "deepseek/DeepSeek-V3-0324",
    "kimi":                 "moonshotai/kimi-k2.6",
    "nemotron":             "nvidia/nemotron-3-super-120b-a12b:free",
    "glm":                  "@cf/zai-org/glm-5.2",
    "compound":             "compound-beta",
    "gemini_paid_founder":  "gemini-3.5-flash",
    "gemini_paid_ultra":    "gemini-3.1-flash-lite",
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

def extract_horizon_result(query, ctx, attempt=1, max_attempts=3):
    if attempt > max_attempts:
        return ERR_HORIZON
        
    # Liste des clés obligatoires demandées par le front-end pour la matrice Horizon
    required_matrix_keys = [
        "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible",
        "qu_en_pensent_les_gens", "quelles_sont_les_alternatives",
        "quels_sont_les_risques", "quelle_option_est_recommandee"
    ]
    
    # Nouvelle cascade configurée selon tes directives
    horizon_steps = [
        (client_nvidia,      "kimi",                 20),  # Kimi Free (via NVIDIA) - 20s
        (client_cloudflare,  "glm",                  20),  # GLM Free (via Cloudflare) - 20s
        (client_gemini_paid, "gemini_paid_standard", 25),  # Gemini 2.5 Flash Lite Paid - 25s
    ]
    
    if attempt > len(horizon_steps):
        return ERR_HORIZON
        
    client, model_key, timeout = horizon_steps[attempt - 1]
    
    # Si le client n'est pas configuré ou si le modèle est temporairement verrouillé
    if client is None or (attempt < len(horizon_steps) and is_model_locked(model_key)):
        return extract_horizon_result(query, ctx, attempt + 1, max_attempts)
        
    try:
        # Appel API selon le SDK requis
        if client in (client_gemini_free, client_gemini_paid):
            r = call_gemini(client, model_key, ctx, timeout=timeout)
            parsed = clean_and_parse_horizon_json(r.text)
        else:
            r = call_openai(client, model_key, ctx, temp=0.1, timeout=float(timeout))
            parsed = clean_and_parse_horizon_json(r)
            
        # Validation stricte de la structure JSON attendue
        has_response   = "response"   in parsed and parsed["response"]
        has_attributes = "attributes" in parsed and isinstance(parsed["attributes"], list)
        has_matrix     = (
            "matrix" in parsed
            and isinstance(parsed["matrix"], dict)
            and all(k in parsed["matrix"] for k in required_matrix_keys)
        )
        
        if not has_response or not has_attributes or not has_matrix:
            print(f"[HORIZON] Tentative {attempt} - structure incomplete.")
            lock_model(model_key)
            return extract_horizon_result(query, ctx, attempt + 1, max_attempts)
            
        # Si on a dû se rabattre sur le dernier modèle gratuit (ou payant si configuré ainsi), on incrémente le compteur global
        if attempt == len(horizon_steps):
            increment_failover_count()
            
        return parsed
        
    except Exception as e:
        print(f"[HORIZON] Erreur tentative {attempt} ({model_key}): {e}")
        lock_model(model_key)
        return extract_horizon_result(query, ctx, attempt + 1, max_attempts)

@app.route("/horizon", methods=["POST"])
def horizon():
    try:
        data  = request.json or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "L'intention d'exploration est vide."}), 400
            
        # Forçage du prompt système pour la structure JSON attendue
        data["message"] = (
            f"Fais une recherche web complete et extrait tout sur : {query}. "
            f"Reponds OBLIGATOIREMENT en JSON valide avec les cles : response, attributes, matrix."
        )
        
        ctx = prepare_shared_context(data, source_override="horizonweb")
        
        # Si l'utilisateur est un membre Premium/Ultra/Founder, on évite la cascade gratuite et on cible directement le modèle payant assigné
        if ctx["user_tier"] != "connected_free":
            tier      = ctx["user_tier"]
            model_key = "gemini_paid_founder" if tier == "founder" else "gemini_paid_standard"
            try:
                r = call_gemini(client_gemini_paid, model_key, ctx, timeout=25)
                return jsonify(clean_and_parse_horizon_json(r.text))
            except Exception as e:
                print(f"[HORIZON PAID] Echec ({e})")
                return jsonify(ERR_HORIZON), 500
                
        # Sécurité anti-abus pour le niveau gratuit
        if get_failover_count() >= MAX_FREE_FAILOVERS:
            return jsonify(ERR_QUOTA)
            
        # Lancement de la nouvelle cascade
        result = extract_horizon_result(query, ctx)
        return jsonify(result)
        
    except Exception as e:
        print(f"Erreur critique /horizon: {e}")
        return jsonify(ERR_HORIZON), 500

@app.route("/home", methods=["POST"])
def home():
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="home")
        if ctx["user_tier"] != "connected_free":
            return jsonify(run_paid_cascade(ctx))
        steps = [
            (client_gemini_free, "gemini_free_2",        4),
            (client_cloudflare,  "glm",                  4),
            (client_gemini_free, "gemini_free_1",        4),
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
            (client_gemini_free, "gemini_free_1",        4),
            (client_nvidia,      "kimi",                 4),
            (client_gemini_free, "gemini_free_2",        4),
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
            (client_openrouter,  "nemotron",             5),
            (client_github,      "deepseek",             5),
            (client_groq,        "compound",             5),
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
                "Genere le passage et termine with :\n<<<INJECT_TEXT>>>\n[texte propre sans HTML]\n<<<END_INJECT>>>"
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
                (client_openrouter,  "nemotron",             5),
                (client_nvidia,      "kimi",                 5),
                (client_cloudflare,  "glm",                  5),
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

def extract_horizon_result(query, ctx, attempt=1, max_attempts=3):
    if attempt > max_attempts:
        return ERR_HORIZON
    required_matrix_keys = [
        "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible",
        "qu_en_pensent_les_gens", "quelles_sont_les_alternatives",
        "quels_sont_les_risques", "quelle_option_est_recommandee"
    ]
    horizon_steps = [
        (client_openrouter,  "nemotron",             20),
        (client_gemini_free, "gemini_free_2",        20),
        (client_gemini_paid, "gemini_paid_standard", 25),
    ]
    if attempt > len(horizon_steps):
        return ERR_HORIZON
    client, model_key, timeout = horizon_steps[attempt - 1]
    if client is None or (attempt < len(horizon_steps) and is_model_locked(model_key)):
        return extract_horizon_result(query, ctx, attempt + 1, max_attempts)
    try:
        if client in (client_gemini_free, client_gemini_paid):
            r      = call_gemini(client, model_key, ctx, timeout=timeout)
            parsed = clean_and_parse_horizon_json(r.text)
        else:
            r      = call_openai(client, model_key, ctx, temp=0.1, timeout=float(timeout))
            parsed = clean_and_parse_horizon_json(r)
        has_response   = "response"   in parsed and parsed["response"]
        has_attributes = "attributes" in parsed and isinstance(parsed["attributes"], list)
        has_matrix     = (
            "matrix" in parsed
            and isinstance(parsed["matrix"], dict)
            and all(k in parsed["matrix"] for k in required_matrix_keys)
        )
        if not has_response or not has_attributes or not has_matrix:
            print(f"[HORIZON] Tentative {attempt} - structure incomplete.")
            lock_model(model_key)
            return extract_horizon_result(query, ctx, attempt + 1, max_attempts)
        if attempt == len(horizon_steps):
            increment_failover_count()
        return parsed
    except Exception as e:
        print(f"[HORIZON] Erreur tentative {attempt} ({model_key}): {e}")
        lock_model(model_key)
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
        if ctx["user_tier"] != "connected_free":
            tier      = ctx["user_tier"]
            model_key = "gemini_paid_founder" if tier == "founder" else "gemini_paid_standard"
            try:
                r = call_gemini(client_gemini_paid, model_key, ctx, timeout=25)
                return jsonify(clean_and_parse_horizon_json(r.text))
            except Exception as e:
                print(f"[HORIZON PAID] Echec ({e})")
                return jsonify(ERR_HORIZON), 500
        if get_failover_count() >= MAX_FREE_FAILOVERS:
            return jsonify(ERR_QUOTA)
        result = extract_horizon_result(query, ctx)
        return jsonify(result)
    except Exception as e:
        print(f"Erreur critique /horizon: {e}")
        return jsonify(ERR_HORIZON), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)