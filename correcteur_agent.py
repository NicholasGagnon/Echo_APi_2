# correcteur_agent.py
import os
import sys
import time
import json
import logging
from flask import Blueprint, request, jsonify
from google import genai
from google.genai import types
from openai import OpenAI
import httpx
from dotenv import load_dotenv

from prompts_correcteur import get_correcteur_system_prompt, get_correcteur_user_prompt

load_dotenv()
logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)

# ── BLUEPRINT FLASK ──────────────────────────────────────────────────────────
correcteur_bp = Blueprint('correcteur_bp', __name__)

# ── CLÉS & CLIENTS ───────────────────────────────────────────────────────────
API_KEY_PAID      = os.getenv("API_KEY_PAID", "").strip()
REQUESTY_API_KEY  = os.getenv("REQUESTY_API_KEY", "").strip()
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "").strip()

_shared_http_client = httpx.Client(timeout=90.0)

client_gemini_paid = genai.Client(api_key=API_KEY_PAID) if API_KEY_PAID else None
client_requesty = (
    OpenAI(base_url="https://router.requesty.ai/v1", api_key=REQUESTY_API_KEY, http_client=_shared_http_client)
    if REQUESTY_API_KEY else None
)
client_deepseek = (
    OpenAI(base_url="https://api.deepseek.com", api_key=DEEPSEEK_API_KEY, http_client=_shared_http_client)
    if DEEPSEEK_API_KEY else None
)

# ── FAMILLES DISPONIBLES ─────────────────────────────────────────────────────
FAMILIES = {
    "deepseek": {"provider": "ds", "model_id": "DeepSeek-V4-Flash-0731"},
    "gemini":   {"provider": "g",  "model_id": "gemini-2.5-flash-lite"},
    "grok":     {"provider": "rq", "model_id": "grok-4-fast-non-reasoning"},
    "chatgpt":  {"provider": "rq", "model_id": "gpt-4o-mini"},
}

MAX_RETRIES_PER_STEP = 3
RETRY_DELAY_SECONDS = 2.0


def execute_llm_call(provider: str, model_id: str, system_prompt: str, user_prompt: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if provider == "rq":
        if client_requesty is None:
            raise RuntimeError("Requesty indisponible.")
        res = client_requesty.chat.completions.create(
            model=model_id, messages=messages, temperature=0.3, max_tokens=32000, timeout=90.0
        )
        finish_reason = res.choices[0].finish_reason
        print(f"[FINISH_REASON] {model_id} (rq) -> {finish_reason}")
        return res.choices[0].message.content or ""

    elif provider == "ds":
        if client_deepseek is None:
            raise RuntimeError("DeepSeek indisponible.")
        res = client_deepseek.chat.completions.create(
            model=model_id, messages=messages, temperature=0.3, max_tokens=32000, timeout=90.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        finish_reason = res.choices[0].finish_reason
        print(f"[FINISH_REASON] {model_id} (ds) -> {finish_reason}")
        return res.choices[0].message.content or ""

    elif provider == "g":
        if client_gemini_paid is None:
            raise RuntimeError("Client Gemini non configuré.")
        contents = [{"role": "user", "parts": [types.Part.from_text(text=user_prompt)]}]
        res = client_gemini_paid.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=16000,
                temperature=0.3,
            ),
        )
        return res.text or ""

    raise RuntimeError(f"Provider inconnu : {provider}")


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.strip()


def parse_step_response(raw_text: str) -> dict:
    cleaned = strip_code_fences(raw_text)
    print(f"[RÉPONSE BRUTE DU MODÈLE — {len(cleaned)} caractères]\n{cleaned[:2000]}{'...(tronqué)' if len(cleaned) > 2000 else ''}\n")
    try:
        data = json.loads(cleaned)
        texte = data.get("texte", "").strip()
        erreurs = data.get("erreurs", [])
        if not texte:
            raise ValueError("Champ 'texte' vide dans le JSON.")
        if not isinstance(erreurs, list):
            erreurs = [str(erreurs)]
        return {"texte": texte, "erreurs": erreurs}
    except (json.JSONDecodeError, ValueError):
        print(f"[PARSING SECOURS] Réponse non-JSON reçue, texte brut conservé.")
        return {"texte": cleaned, "erreurs": ["(format JSON non respecté par le modèle)"]}


def run_step_with_retries(provider: str, model_id: str, system_prompt: str, user_prompt: str) -> dict:
    last_error = None
    for attempt in range(1, MAX_RETRIES_PER_STEP + 1):
        try:
            logging.info(f"[CORRECTEUR] Tentative {attempt}/{MAX_RETRIES_PER_STEP} sur {model_id}")
            raw = execute_llm_call(provider, model_id, system_prompt, user_prompt)
            if not raw.strip():
                raise ValueError("Réponse vide.")
            return parse_step_response(raw)
        except Exception as e:
            last_error = e
            print(f"[ÉCHEC TENTATIVE {attempt}] {model_id} : {e}")
            if attempt < MAX_RETRIES_PER_STEP:
                time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Échec après {MAX_RETRIES_PER_STEP} tentatives sur {model_id} : {last_error}")


@correcteur_bp.route("/api/correcteur/step", methods=["POST"])
def correcteur_step():
    try:
        data = request.json or {}
        original = data.get("original", "").strip()
        family = data.get("family", "").strip()
        step = int(data.get("step", 0))
        previous_text = data.get("previous_text", "").strip()
        previous_errors = data.get("previous_errors", [])

        if not original:
            return jsonify({"error": "Le texte original est vide."}), 400
        if family not in FAMILIES:
            return jsonify({"error": f"Famille inconnue : {family}"}), 400
        if step not in (1, 2, 3, 4):
            return jsonify({"error": "L'étape doit être 1, 2, 3 ou 4."}), 400
        if step > 1 and not previous_text:
            return jsonify({"error": f"L'étape {step} nécessite le texte de l'étape précédente."}), 400

        provider = FAMILIES[family]["provider"]
        model_id = FAMILIES[family]["model_id"]

        system_prompt = get_correcteur_system_prompt(step)
        user_prompt = get_correcteur_user_prompt(original, step, previous_text, previous_errors)

        result = run_step_with_retries(provider, model_id, system_prompt, user_prompt)

        return jsonify({
            "step": step,
            "family": family,
            "model_used": model_id,
            "texte": result["texte"],
            "erreurs": result["erreurs"],
        })

    except Exception as e:
        print(f"[CORRECTEUR CRITICAL] {e}")
        return jsonify({"error": f"Erreur d'infrastructure : {e}"}), 500


# ── CASCADE DE GÉNÉRATION DE CONTRAT D'ACHAT ────────────────────────────────
CONTRAT_CASCADE = [
    {"provider": "rq", "model_id": "grok-4-fast-non-reasoning", "label": "Grok (Requesty)"},
    {"provider": "ds", "model_id": "deepseek-v4-flash",         "label": "DeepSeek"},
    {"provider": "rq", "model_id": "grok-4-fast-non-reasoning", "label": "Grok (Secours)"},
]


def generate_contrat_with_cascade(free_text: str, lang: str, date_str: str) -> dict:
    system_prompt = (
        "Tu es un expert juridique spécialisé en rédaction de contrats de vente de gré à gré au Québec (Canada). "
        "Ta mission est d'analyser les informations fournies et de retourner EXCLUSIVEMENT un objet JSON valide "
        "sans aucune clôture de code (pas de ```json), contenant les champs exacts suivants :\n"
        "{\n"
        '  "vendeur_nom": "Nom du vendeur",\n'
        '  "vendeur_adresse": "Adresse du vendeur",\n'
        '  "acheteur_nom": "Nom de l\'acheteur",\n'
        '  "acheteur_adresse": "Adresse de l\'acheteur",\n'
        '  "description_bien": "Description détaillée et précise du bien",\n'
        '  "prix_total": "Prix total avec symbole monétaire",\n'
        '  "modalites_paiement": "Détails et modalités du paiement",\n'
        '  "date": "YYYY-MM-DD",\n'
        '  "notes": "Notes légales ou clauses particulières si nécessaires"\n'
        "}"
    )

    user_prompt = f"Langue souhaitée: {lang}\nDate: {date_str}\nInformations brutes:\n{free_text}"

    last_error = None
    for step_info in CONTRAT_CASCADE:
        provider = step_info["provider"]
        model_id = step_info["model_id"]
        label = step_info["label"]

        try:
            logging.info(f"[CONTRAT] Tentative sur {label} ({model_id})...")
            raw = execute_llm_call(provider, model_id, system_prompt, user_prompt)
            if not raw.strip():
                raise ValueError("Réponse vide du modèle.")

            cleaned = strip_code_fences(raw)
            data = json.loads(cleaned)

            if "description_bien" in data and "prix_total" in data:
                data["model_used"] = model_id
                return data
            else:
                raise ValueError("JSON incomplet.")

        except Exception as e:
            last_error = e
            logging.warning(f"[CONTRAT ÉCHEC] {label} a échoué : {e}. Passage au fallback suivant...")
            time.sleep(1.0)

    raise RuntimeError(f"Toute la cascade a échoué. Dernière erreur : {last_error}")


@correcteur_bp.route("/1/generate-contrat", methods=["POST"])
def generate_contrat_endpoint():
    try:
        data = request.json or {}
        free_text = data.get("freeText", "").strip()
        lang = data.get("lang", "fr").strip()
        date_str = data.get("dateStr", "").strip()

        if not free_text:
            return jsonify({"error": "Les informations du contrat sont vides."}), 400

        result = generate_contrat_with_cascade(free_text, lang, date_str)
        return jsonify(result)

    except Exception as e:
        logging.error(f"[CONTRAT CRITICAL] {e}")
        return jsonify({"error": f"Erreur lors de la génération : {str(e)}"}), 500


@correcteur_bp.route("/ping-correcteur")
def ping_correcteur():
    return jsonify({"status": "correcteur_engine_online"})