# contenu_agent.py
import os
import sys
import re
import logging
from flask import Blueprint, request, jsonify
from google import genai
from google.genai import types
from openai import OpenAI
import httpx
from dotenv import load_dotenv

from prompts_contenu import (
    get_prompt_createur_system, get_prompt_createur_user,
    get_decoupage_system, get_decoupage_user,
    get_prompt_bloc_system, get_prompt_bloc_user,
    get_prompt_raccord_system, get_prompt_raccord_user
)

load_dotenv()
logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)

# ── BLUEPRINT FLASK ──────────────────────────────────────────────────────────
contenu_bp = Blueprint('contenu_bp', __name__)

# ── CLÉS & CLIENTS ──────────────────────────────────────────────────────────
API_KEY_PAID      = os.getenv("API_KEY_PAID", "").strip()
REQUESTY_API_KEY  = os.getenv("REQUESTY_API_KEY", "").strip()
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "").strip()

_shared_http_client = httpx.Client(timeout=300.0)

client_gemini_paid = genai.Client(api_key=API_KEY_PAID) if API_KEY_PAID else None
client_requesty = (
    OpenAI(base_url="https://router.requesty.ai/v1", api_key=REQUESTY_API_KEY, http_client=_shared_http_client)
    if REQUESTY_API_KEY else None
)
client_deepseek = (
    OpenAI(base_url="https://api.deepseek.com", api_key=DEEPSEEK_API_KEY, http_client=_shared_http_client)
    if DEEPSEEK_API_KEY else None
)

MODEL_DEEPSEEK = {"provider": "ds", "model_id": "deepseek-v4-flash"}
MODEL_GROK     = {"provider": "rq", "model_id": "xai/grok-4-fast-non-reasoning"}

# Cascade unifiée utilisée par toutes les routes : DeepSeek → Grok-4-Fast-Non-Reasoning (Requesty) → DeepSeek
CASCADE_STEPS = [MODEL_DEEPSEEK, MODEL_GROK, MODEL_DEEPSEEK]


def nettoie_formatage_impression(texte: str) -> str:
    if not texte:
        return ""
    t = texte.strip()
    t = re.sub(r'^```markdown\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^```html\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^```\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def execute_llm_call(provider: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if provider == "rq":
        if client_requesty is None:
            raise RuntimeError("Requesty non configuré.")
        res = client_requesty.chat.completions.create(
            model=model_id, messages=messages, temperature=0.7, max_tokens=25000, timeout=300.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return res.choices[0].message.content or ""

    elif provider == "ds":
        if client_deepseek is None:
            raise RuntimeError("DeepSeek non configuré.")
        res = client_deepseek.chat.completions.create(
            model=model_id, messages=messages, temperature=0.3, max_tokens=32000, timeout=300.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return res.choices[0].message.content or ""

    elif provider == "g":
        if client_gemini_paid is None:
            raise RuntimeError("Client Gemini non configuré.")
        contents = [{"role": "user", "parts": [types.Part.from_text(text=user_prompt)]}]
        res = client_gemini_paid.models.generate_content(
            model=model_id, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt, max_output_tokens=20000, temperature=0.8,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return res.text or ""

    raise RuntimeError(f"Provider inconnu : {provider}")


def execute_cascade(system_prompt: str, user_prompt: str, label: str = "") -> str:
    """Cascade DeepSeek → Grok-4-Fast-Non-Reasoning (Requesty) → DeepSeek, utilisée par toutes les routes."""
    last_err = None
    for i, step in enumerate(CASCADE_STEPS):
        try:
            texte = execute_llm_call(step["provider"], step["model_id"], system_prompt, user_prompt)
            if texte and texte.strip():
                if i > 0:
                    print(f"[{label}] {step['model_id']} OK (essai {i + 1})")
                return texte
            print(f"[{label}] {step['model_id']} a renvoyé une réponse vide (essai {i + 1})")
        except Exception as e:
            last_err = e
            print(f"[{label}] {step['model_id']} échec (essai {i + 1}) ({e})")
    raise RuntimeError(f"Tous les modèles ont échoué pour {label} : {last_err}")


@contenu_bp.route("/api/contenu/prompt-maitre", methods=["POST"])
def route_prompt_maitre():
    try:
        data = request.json or {}
        sujet = data.get("sujet", "").strip()
        type_contenu = data.get("type_contenu", "guide_100")
        if not sujet:
            return jsonify({"error": "Le sujet est vide."}), 400

        sys_p = get_prompt_createur_system(type_contenu)
        usr_p = get_prompt_createur_user(sujet, type_contenu)

        texte = execute_cascade(sys_p, usr_p, label="PROMPT-MAITRE")

        return jsonify({"prompt_maitre": texte.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contenu_bp.route("/api/contenu/decoupage", methods=["POST"])
def route_decoupage():
    try:
        data = request.json or {}
        prompt_maitre = data.get("prompt_maitre", "").strip()
        nb_points = int(data.get("nb_points", 600))

        sys_p = get_decoupage_system(nb_points)
        usr_p = get_decoupage_user(prompt_maitre, nb_points)

        texte = execute_cascade(sys_p, usr_p, label="DECOUPAGE")

        return jsonify({"liste_points": texte})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contenu_bp.route("/api/contenu/generer-bloc", methods=["POST"])
def route_generer_bloc():
    try:
        data = request.json or {}
        prompt_maitre = data.get("prompt_maitre", "").strip()
        tranche = data.get("tranche", "").strip()
        numero = data.get("numero", 1)
        total = data.get("total", 6)
        type_contenu = data.get("type_contenu", "guide_100")

        sys_p = get_prompt_bloc_system(type_contenu)
        usr_p = get_prompt_bloc_user(prompt_maitre, tranche, numero, total)

        texte_brut = execute_cascade(sys_p, usr_p, label=f"BLOC {numero}")

        return jsonify({"texte_bloc": nettoie_formatage_impression(texte_brut)})
    except Exception as e:
        print(f"[ERREUR BLOC {numero}] : {e}")
        return jsonify({"error": str(e)}), 500


@contenu_bp.route("/api/contenu/generer-raccord", methods=["POST"])
def route_generer_raccord():
    try:
        data = request.json or {}
        fin_a = data.get("fin_a", "").strip()
        debut_b = data.get("debut_b", "").strip()

        sys_p = get_prompt_raccord_system()
        usr_p = get_prompt_raccord_user(fin_a, debut_b)

        texte = execute_cascade(sys_p, usr_p, label="RACCORD")

        return jsonify({"texte_raccord": nettoie_formatage_impression(texte)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500