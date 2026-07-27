# ollama.py
import os
import json
from flask import Blueprint, request, Response, stream_with_context, jsonify
from openai import OpenAI
import httpx

# ── CONFIGURATION OLLAMA ───────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip()
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "gemma4:12b").strip()

_ollama_http_client = httpx.Client(timeout=180.0)

client_ollama = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
    http_client=_ollama_http_client,
    max_retries=0
)

ollama_bp = Blueprint("ollama_bp", __name__)


@ollama_bp.route("/ollama/ping", methods=["GET"])
def ollama_ping():
    """Vérifie si l'instance Ollama locale est accessible."""
    try:
        res = client_ollama.models.list()
        models = [m.id for m in res.data]
        return jsonify({"status": "online", "model_target": OLLAMA_MODEL, "available_models": models}), 200
    except Exception as e:
        return jsonify({"status": "offline", "error": str(e)}), 503


@ollama_bp.route("/ollama/warmup", methods=["POST"])
def ollama_warmup():
    """Préchauffe le modèle gemma4:12b en VRAM."""
    try:
        print(f"[OLLAMA WARMUP] Démarrage du préchauffage de {OLLAMA_MODEL}...")
        client_ollama.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            timeout=180.0
        )
        print(f"[OLLAMA WARMUP] Modèle {OLLAMA_MODEL} prêt !")
        return jsonify({"status": "ready"}), 200
    except Exception as e:
        print(f"[OLLAMA WARMUP ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@ollama_bp.route("/localisation-chat", methods=["POST"])
def localisation_chat():
    """Route de chat en mode STREAMING (mot par mot) pour éviter la latence."""
    try:
        data = request.json or {}
        user_message = data.get("message", "")
        raw_history  = data.get("history", [])

        messages = [{"role": "system", "content": "Tu es un assistant IA exécuté en local sur la machine."}]

        # On limite à 6 messages d'historique pour garder la vitesse GPU optimale
        for msg in raw_history[-6:]:
            if not isinstance(msg, str):
                continue
            if msg.startswith("You:") or msg.startswith("Toi:"):
                messages.append({"role": "user", "content": msg.split(":", 1)[1].strip()})
            elif msg.startswith("Echo:"):
                messages.append({"role": "assistant", "content": msg.split(":", 1)[1].strip()})

        if user_message:
            messages.append({"role": "user", "content": user_message})

        def generate():
            response = client_ollama.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                temperature=0.7,
                stream=True  # Envoie le texte au fur et à mesure
            )
            for chunk in response:
                content = chunk.choices[0].delta.content or ""
                if content:
                    yield f"data: {json.dumps({'content': content})}\n\n"

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    except Exception as e:
        print(f"[OLLAMA ERROR] {e}")
        return Response("data: {\"content\": \"Erreur de connexion à Ollama.\"}\n\n", mimetype="text/event-stream")