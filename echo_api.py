import os
import json
import re
import base64
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
from openai import OpenAI
from dotenv import load_dotenv

# IMPORTATION DU FICHIER PROMPTS
from prompts import generate_system_prompt

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── CONFIGURATION DES CLÉS D'API (SECTION PAYANTE UNIQUEMENT) ─────────
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

# ── INITIALISATION DES CLIENTS API PAYANTS ───────────────────────────
client_gemini_paid = genai.Client(api_key=API_KEY_PAID) if API_KEY_PAID else None
client_openrouter  = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
client_github      = OpenAI(base_url=GITHUB_BASE_URL,     api_key=GITHUB_API_KEY)     if GITHUB_API_KEY     else None
client_nvidia      = OpenAI(base_url=NVIDIA_BASE_URL,     api_key=NVIDIA_API_KEY)     if NVIDIA_API_KEY     else None
client_groq        = OpenAI(base_url=GROQ_BASE_URL,       api_key=GROQ_API_KEY)       if GROQ_API_KEY       else None
client_cloudflare  = OpenAI(base_url=CLOUDFLARE_BASE_URL, api_key=CLOUDFLARE_API_TOKEN) if CLOUDFLARE_API_TOKEN else None

# ── PARSAGE ET NETTOYAGE DU JSON DE RETOUR ────────────────────────────
def clean_and_parse_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "response" in parsed:
            return parsed
    except Exception:
        pass

    match_array = re.search(r'\[\s*(\{.*?\})\s*,?', text, re.DOTALL)
    if match_array:
        try:
            parsed = json.loads(match_array.group(1))
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

# ── COMPILATION DES CONTENUS DU CHAT POUR GEMINI ─────────────────────
def build_gemini_contents(historique_reduit: list, image_b64: str | None, user_message: str, force_neutral_style: bool) -> list:
    contents = []

    for msg in historique_reduit:
        if not isinstance(msg, str) or msg.startswith("__IMAGE__:"):
            continue
        clean_content = msg.split(":", 1)[1].strip() if ":" in msg else msg.strip()
        if "action limit reached" in clean_content.lower() or "do it for you" in clean_content.lower() or clean_content == "...":
            continue

        if msg.startswith("You:") or msg.startswith("Toi:"):
            contents.append({
                "role": "user",
                "parts": [types.Part.from_text(text=clean_content)]
            })
        elif msg.startswith("Echo:"):
            try:
                parsed = json.loads(clean_content)
                clean_content = parsed.get("response", clean_content)
            except Exception:
                pass
            
            if force_neutral_style:
                clean_content = "[Analyse technique archivée]"

            contents.append({
                "role": "model",
                "parts": [types.Part.from_text(text=clean_content)]
            })

    last_parts = []

    if image_b64:
        try:
            header, b64data = image_b64.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]
            raw_bytes = base64.b64decode(b64data)
            last_parts.append(types.Part.from_bytes(data=raw_bytes, mime_type=mime_type))
            print(f"[IMAGE] Injectée : {mime_type}, {len(raw_bytes)} bytes")
        except Exception as e:
            print(f"[WARN] Image decode error : {e} — envoi sans image")

    text_to_send = user_message or "Analyse cette image et décris ce que tu vois."
    last_parts.append(types.Part.from_text(text=text_to_send))

    contents.append({
        "role": "user",
        "parts": last_parts
    })

    return contents

# ── ROUTE DE SANTÉ (CRITIQUE POUR LES DÉPLOIEMENTS RAILWAY/RENDER) ────
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "online",
        "message": "Le sillage d'Echo réinventé est parfaitement aligné en production.",
        "presence": "Echo",
        "timestamp": datetime.now().isoformat()
    }), 200

# ── ROUTE PRINCIPALE DE DISCUSSION /CHAT ─────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data             = request.json or {}
        user_message     = data.get("message", "")
        calendar_events = data.get("calendarEvents", {})
        raw_history      = data.get("history", [])
        source           = data.get("source", "chat").lower().strip()
        image_b64        = data.get("image", None)
        selected_buttons = data.get("selectedButtons", [])

        # ── 🎯 STRATÉGIE DE RÉINVENTION DU FORFAIT GRATUIT ──
        raw_tier = data.get("userTier", "free").lower().strip()
        user_tier = "premium" if raw_tier == "free" else raw_tier

        # Extraction des paramètres de l'outil Vitalité
        current_expenses = data.get("currentExpenses", [])
        current_calories = data.get("currentCalories", [])
        current_cycle    = data.get("currentCycle", "mois")

        has_image = bool(image_b64)
        print(f"[DEBUG] message: '{user_message[:60]}' | tier orig: '{raw_tier}' -> forcé: '{user_tier}' | source: '{source}'")

        maintenant       = datetime.now()
        date_aujourdhui  = maintenant.strftime("%A %d %B %Y")
        annee_en_cours   = maintenant.strftime("%Y")

        # Filtrage des événements du calendrier (fenêtre de 31 jours)
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
            print(f"[WARN] Erreur filtrage calendrier : {e}")
            filtered_calendar = calendar_events

        # ── APPEL DE LA LOGIQUE EXTERNALISÉE DU PROMPT SYSTÈME ─────────
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

        # ── ANTI-DOUBLONS CRITIQUE ──
        anti_duplication_directive = (
            "\n\nCRITICAL SAFETY DIRECTIVE FOR ACTION EXTRACTION:\n"
            "You are provided with a partial chat history for baseline conversational context. However, you MUST ONLY "
            "trigger or extract updates for structural tools (like adding calendar events, logging calories, or recording expenses) "
            "if the intent is explicitly and newly demanded in the LATEST message from the user. "
            "If the latest user message is conversational, neutral, or just a reply to your previous text, you MUST return "
            "'action': null, even if earlier blocks of the chat history contain command sentences. "
            "Never repeat or re-execute a past action from historical text."
        )
        system_prompt = base_system_prompt + anti_duplication_directive

        # =====================================================================
        # AJUSTEMENT DYNAMIQUE DE LA MÉMOIRE SELON LE FORFAIT REDIRIGÉ
        # =====================================================================
        if user_tier in ["basic", "premium"]:
            taille_memoire = 15
            output_tokens = 2048
        elif user_tier in ["ultra", "founder"]:
            taille_memoire = 30
            output_tokens = 4096
        else:
            taille_memoire = 15
            output_tokens = 2048

        # Extraction fine des derniers messages
        historique_ajuste = raw_history[-taille_memoire:] if len(raw_history) > taille_memoire else raw_history

        has_active_buttons = len(selected_buttons) > 0
        gemini_contents = build_gemini_contents(
            historique_reduit=historique_ajuste, 
            image_b64=image_b64, 
            user_message=user_message, 
            force_neutral_style=has_active_buttons or (source == "vitality")
        )

        # ── INJECTION SÉCURISÉE GEMINI SANS CONTRAINTE JSON STRICTE (ANTI-CRASH) ──
        def call_gemini(client, model_name):
            return client.models.generate_content(
                model=model_name,
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=output_tokens,
                    tools=[{"google_search": {}}]
                )
            )

        # =====================================================================
        # ROUTAGE DE PRODUCTION UNIQUE (SOUVERAINETÉ ET ROUTAGE ULTRA-STABLE)
        # =====================================================================
        if not client_gemini_paid:
            return jsonify({"action": None, "response": "Configuration d'API payante introuvable."}), 500

        # ── FORFAIT INTERMÉDIAIRE & ANCIEN GRATUIT REDIRIGÉ (BASIC / PREMIUM) ──
        if user_tier in ["basic", "premium"]:
            try:
                print("[PAID] -> Gemini 3.1 Flash-Lite Premium")
                r = call_gemini(client_gemini_paid, "gemini-3.1-flash-lite")
                return jsonify(clean_and_parse_json(r.text))
            except Exception as e:
                print(f"⚠️ [FAILOVER BASIC/PREMIUM] Erreur 3.1 Lite ({e}). Bascule sur 2.5 Flash-Lite...")
                try:
                    r = call_gemini(client_gemini_paid, "gemini-2.5-flash-lite")
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as fallback_error:
                    print(f"✕ Échec critique du failover Basic/Premium : {fallback_error}")
                    return jsonify({"action": None, "response": "Je ressens une petite déconnexion, redonne-moi une seconde ! 😎"})

        # ── FORFAIT HAUTE PERFORMANCE (ULTRA) ───────────────────────────────
        elif user_tier == "ultra":
            try:
                print("[PAID - ULTRA] -> Gemini 3.1 Flash-Lite Payant")
                r = call_gemini(client_gemini_paid, "gemini-3.1-flash-lite")
                return jsonify(clean_and_parse_json(r.text))
            except Exception as e:
                print(f"⚠️ [FAILOVER ULTRA] Gemini 3.1 Lite saturé ({e}). Bascule de puissance sur 2.5 Flash complet...")
                try:
                    r = call_gemini(client_gemini_paid, "gemini-2.5-flash")
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as fallback_error:
                    print(f"✕ Échec critique du failover Ultra : {fallback_error}")
                    return jsonify({"action": None, "response": "Mon sillage Ultra tangue un peu. Réessaie ! 😎"})

        # ── FORFAIT ÉLITE / HISTORIQUE (FOUNDER) ────────────────────────────
        elif user_tier == "founder":
            try:
                print("[PAID - FOUNDER] -> Gemini 3.0 Flash Preview")
                r = call_gemini(client_gemini_paid, "gemini-3-flash-preview")
                return jsonify(clean_and_parse_json(r.text))
            except Exception as e:
                print(f"⚠️ [FAILOVER FOUNDER] Erreur sur Gemini 3.0 ({e}). Bascule immédiate sur 2.5 Flash...")
                try:
                    r = call_gemini(client_gemini_paid, "gemini-2.5-flash")
                    return jsonify(clean_and_parse_json(r.text))
                except Exception as fallback_error:
                    print(f"✕ Échec critique du failover Founder : {fallback_error}")
                    return jsonify({"action": None, "response": "Même les fondateurs ont parfois des vagues. Réessaie ! 😎"})

        else:
            return jsonify({"action": None, "response": "Plan utilisateur non reconnu."}), 400

    except Exception as e:
        print(f"Erreur critique Flask : {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"action": None, "response": "Système instable, réessaie ton message !"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🔥 Serveur Echo connecté et aligné sur le port {port}...")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )