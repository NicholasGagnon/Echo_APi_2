# style_agent.py
import os
import sys
import time
import logging
from datetime import datetime, timedelta
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
from openai import OpenAI
import httpx
from dotenv import load_dotenv

# Importation de tes invites configurés pour STYLE
from prompts_style import get_style_system_prompt, get_style_user_prompt

# Initialisation de l'environnement et logging
load_dotenv()
logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)

app = Flask(__name__)
CORS(app)

# ── CONFIGURATION DES CLÉS & CLIENTS ALIGNÉS SUR ECHO_API ───────────────────
API_KEY_PAID       = os.getenv("API_KEY_PAID", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
REQUESTY_API_KEY   = os.getenv("REQUESTY_API_KEY", "").strip()
DEEPSEEK_API_KEY   = os.getenv("DEEPSEEK_API_KEY", "").strip()

_shared_http_client = httpx.Client(timeout=65.0)

# SDK Gemini Officiel (pour appeler ton Gemini 2.5 Flash Lite en direct chez Google)
client_gemini_paid = genai.Client(api_key=API_KEY_PAID) if API_KEY_PAID else None

client_openrouter = (
    OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY, http_client=_shared_http_client)
    if OPENROUTER_API_KEY else None
)
client_requesty = (
    OpenAI(base_url="https://router.requesty.ai/v1", api_key=REQUESTY_API_KEY, http_client=_shared_http_client)
    if REQUESTY_API_KEY else None
)
client_deepseek = (
    OpenAI(base_url="https://api.deepseek.com", api_key=DEEPSEEK_API_KEY, http_client=_shared_http_client)
    if DEEPSEEK_API_KEY else None
)

# ── LOGIQUE DES VERROUS (LOCKS) COPIÉE SUR ECHO_API ───────────────────────────
MODELS_LOCK_REGISTRY = {}
_lock_mutex = threading.Lock()

def is_model_locked(model_id: str) -> bool:
    with _lock_mutex:
        lock_time = MODELS_LOCK_REGISTRY.get(model_id)
        if lock_time:
            if datetime.now() < lock_time:
                return True
            else:
                del MODELS_LOCK_REGISTRY[model_id]
        return False

def lock_model(model_id: str, seconds: int = 30):
    with _lock_mutex:
        MODELS_LOCK_REGISTRY[model_id] = datetime.now() + timedelta(seconds=seconds)
    print(f"[LOCK STYLE] {model_id} hors circuit {seconds}s.")

ERR_FINAL = {"action": None, "response": "Erreur d'infrastructure : le conseil artistique a expiré."}
ERR_CRASH = {"action": None, "response": "Une erreur inattendue s'est produite sur le réseau STYLE."}

# ── REPRÉSENTATION DES MODÈLES DISPONIBLES ───────────────────────────────────
MODELS = {
    "gemini_paid_standard": "gemini-2.5-flash-lite",
    "deepseek": "deepseek-v4-flash",
    "mistral_small_32b": "mistralai/mistral-small-3.2-24b-instruct",
    "gpt_4o_mini": "openai/gpt-4o-mini",
}

# ── CASCADES : chaque round tente son modèle principal 2 fois (délai 3s entre
#    les 2 tentatives), puis bascule sur UN SEUL modèle de secours différent. ──
STYLE_CASCADES = {
    1: [("g", "gemini_paid_standard"), ("g", "gemini_paid_standard"), ("ds", "deepseek")],
    2: [("ds", "deepseek"), ("ds", "deepseek"), ("g", "gemini_paid_standard")],
    3: [("g", "gemini_paid_standard"), ("g", "gemini_paid_standard"), ("ds", "deepseek")],
    4: [("ds", "deepseek"), ("ds", "deepseek"), ("g", "gemini_paid_standard")],
    5: [("g", "gemini_paid_standard"), ("g", "gemini_paid_standard"), ("ds", "deepseek")],
    6: [("ds", "deepseek"), ("ds", "deepseek"), ("g", "gemini_paid_standard")],
    7: [("or", "mistral_small_32b"), ("or", "mistral_small_32b"), ("g", "gemini_paid_standard")],
    8: [("rq", "gpt_4o_mini"), ("ds", "deepseek"), ("rq", "gpt_4o_mini")],
}

# ── LOGIQUE DES APPELS AUX MODÈLES ────────────────────────────────────────────
def execute_style_llm_call(provider: str, model_key: str, system_prompt: str, user_prompt: str) -> str:
    messages_openai = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    model_id = MODELS.get(model_key, model_key)

    if provider == "rq":
        if client_requesty is None: raise RuntimeError("Requesty indisponible.")
        res = client_requesty.chat.completions.create(
            model=model_id, messages=messages_openai, temperature=0.7, max_tokens=12000, timeout=60.0
        )
        finish_reason = res.choices[0].finish_reason
        if finish_reason == "length":
            print(f"[TRONCATURE DÉTECTÉE] {model_key} (rq) a atteint la limite de tokens (finish_reason=length)")
        else:
            print(f"[FINISH_REASON] {model_key} (rq) -> {finish_reason}")
        return res.choices[0].message.content or ""

    elif provider == "or":
        if client_openrouter is None: raise RuntimeError("OpenRouter indisponible.")
        res = client_openrouter.chat.completions.create(
            model=model_id, messages=messages_openai, temperature=0.7, max_tokens=12000, timeout=60.0
        )
        finish_reason = res.choices[0].finish_reason
        if finish_reason == "length":
            print(f"[TRONCATURE DÉTECTÉE] {model_key} (or) a atteint la limite de tokens (finish_reason=length)")
        else:
            print(f"[FINISH_REASON] {model_key} (or) -> {finish_reason}")
        return res.choices[0].message.content or ""

    elif provider == "ds":
        if client_deepseek is None: raise RuntimeError("DeepSeek Direct API indisponible.")
        res = client_deepseek.chat.completions.create(
            model=model_id, messages=messages_openai, temperature=0.6, max_tokens=16000, timeout=75.0
        )
        finish_reason = res.choices[0].finish_reason
        if finish_reason == "length":
            print(f"[TRONCATURE DÉTECTÉE] {model_key} (ds) a atteint la limite de tokens (finish_reason=length)")
        else:
            print(f"[FINISH_REASON] {model_key} (ds) -> {finish_reason}")
        return res.choices[0].message.content or ""

    elif provider == "g":
        if client_gemini_paid is None: raise RuntimeError("Client Gemini non configuré.")
        contents = [{"role": "user", "parts": [types.Part.from_text(text=user_prompt)]}]
        res = client_gemini_paid.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=12000,
                temperature=0.8,
            )
        )
        try:
            finish_reason = res.candidates[0].finish_reason
            if str(finish_reason) in ("MAX_TOKENS", "2"):
                print(f"[TRONCATURE DÉTECTÉE] {model_key} (g) a atteint la limite de tokens (finish_reason={finish_reason})")
            else:
                print(f"[FINISH_REASON] {model_key} (g) -> {finish_reason}")
        except Exception:
            pass
        return res.text or ""

    return ""

def ensure_use_client_directive(code: str) -> str:
    """
    Filet de sécurité : si le composant utilise des hooks React ou des
    gestionnaires d'événements mais que la directive "use client" est absente,
    on l'ajoute automatiquement en première ligne.
    """
    stripped = code.strip()
    if not stripped:
        return code

    first_lines = stripped.splitlines()[:2]
    already_present = any(
        line.strip() in ('"use client";', "'use client';", '"use client"', "'use client'")
        for line in first_lines
    )
    if already_present:
        return stripped

    needs_client = any(
        marker in stripped
        for marker in ("useState", "useEffect", "useRef", "useMemo", "useCallback",
                        "useContext", "useReducer", "onClick", "onChange", "onSubmit")
    )

    if needs_client:
        return '"use client";\n\n' + stripped
    return stripped

def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```tsx"):
        cleaned = cleaned[6:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

def parse_patches(text: str):
    """
    Tente de parser la réponse du modèle comme un tableau JSON de patchs
    [{"old": ..., "new": ...}, ...]. Retourne None si le parsing échoue
    complètement (dans ce cas on bascule sur le mode fichier complet en secours).
    """
    import json
    import re

    cleaned = strip_code_fences(text)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Tentative de secours : extraire le premier tableau JSON valide dans le texte
    match = re.search(r'\[.*\]', cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    return None

def apply_patches(base_code: str, patches: list):
    """
    Applique séquentiellement une liste de patchs {"old":..., "new":...} sur
    le code de base. Les patchs dont le "old" ne correspond pas exactement
    sont ignorés (comptés en échec) sans faire planter la chaîne.

    Garde-fou anti-duplication : si le texte "new" (au-delà d'une simple
    variation mineure) est déjà présent ailleurs dans le code AVANT patch,
    on rejette le patch — c'est le signe d'un "old" mal ciblé qui va créer
    un bloc dupliqué/orphelin plutôt qu'un vrai remplacement.
    """
    working = base_code
    applied = 0
    failed = 0

    for p in patches:
        if not isinstance(p, dict):
            failed += 1
            continue
        old = p.get("old", "")
        new = p.get("new", "")
        if not old:
            failed += 1
            continue
        if old not in working:
            failed += 1
            preview = old[:80].replace("\n", "\\n")
            print(f"[PATCH ÉCHEC] \"old\" introuvable dans le code actuel (longueur={len(old)}) : {preview}...")
            continue

        # Garde-fou anti-"patch géant déguisé" : un "old" trop long signale que le
        # modèle a recopié une section entière au lieu de cibler un point précis.
        # On rejette pour forcer un découpage en patchs plus petits au prochain essai.
        if len(old) > 700:
            failed += 1
            print(f"[PATCH REJETÉ — TROP LONG] \"old\" fait {len(old)} caractères (limite 700) — ressemble à une section entière recopiée plutôt qu'un patch ciblé. Patch ignoré.")
            continue

        # Garde-fou anti-duplication : si "new" est significativement long (>150
        # caractères, donc probablement un bloc JSX complet) et qu'il existe déjà
        # presque à l'identique ailleurs dans le code (hors de la zone qu'on
        # remplace), c'est le signe d'un patch qui va dupliquer un bloc entier.
        if len(new) > 150:
            working_without_old = working.replace(old, "", 1)
            # On compare un extrait significatif de "new" (les 100 premiers
            # caractères non-triviaux) pour détecter une quasi-duplication.
            new_signature = new.strip()[:100]
            if new_signature and new_signature in working_without_old:
                failed += 1
                print(f"[PATCH REJETÉ — DUPLICATION] Le contenu de \"new\" existe déjà ailleurs dans le fichier (risque de bloc dupliqué/orphelin). Patch ignoré.")
                continue

        working = working.replace(old, new, 1)
        applied += 1

    print(f"[PATCH BILAN] {applied} patch(s) appliqué(s), {failed} échec(s)")
    return working, applied, failed

# ── ROUTE /api/style/mutate ──────────────────────────────────────────────────
@app.route("/api/style/mutate", methods=["POST"])
def style_mutate():
    try:
        data = request.json or {}
        question = data.get("question", "").strip() # L'idée de style brute de l'utilisateur
        context = data.get("context", "").strip()   # Le fil de discussion ou le code accumulé
        lang = data.get("lang", "fr").strip()
        round_num = int(data.get("round", 1))

        if not question or round_num < 1 or round_num > 8:
            return jsonify({"error": "Paramètres de flux de style invalides."}), 400

        fallback_chain = STYLE_CASCADES.get(round_num)
        is_final = (round_num == 7) # La fin de la phase de création artistique, avant le correcteur

        # Définition des personas selon les rounds (1 à 8) :
        # - primo (Éclaireur Gemini direct) : Round 1
        # - na (Artiste Traceur) : Rounds 2 et 5
        # - cn (Le Saboteur) : Rounds 3 et 6
        # - eu (Le Master) : Rounds 4 et 7
        # - compilateur : Round 8 — convertit le HTML final en vrai composant React/TSX
        if round_num == 1:
            role_type = "primo"
        elif round_num == 8:
            role_type = "compilateur"
        elif round_num in (2, 5):
            role_type = "na"
        elif round_num in (3, 6):
            role_type = "cn"
        else:  # 4, 7
            role_type = "eu"

        # MODE PATCH activé pour les rounds 1-7 dès qu'il y a du code HTML existant.
        # Le round 8 (compilateur) est TOUJOURS en mode fichier complet : c'est une
        # conversion de format (HTML -> TSX), pas une édition incrémentale.
        patch_mode = bool(context.strip()) and role_type != "compilateur"

        system_prompt = get_style_system_prompt(role_type, lang, patch_mode)
        user_prompt = get_style_user_prompt(question, role_type, lang, context, round_num, is_final, patch_mode)

        print("\n" + "="*60 + f"\n[STYLE PROMPT ENVOYÉ] ROUND {round_num}/8 ({role_type.upper()}) — MODE {'PATCH' if patch_mode else 'FICHIER COMPLET'}\n" + "="*60)
        print(f"USER_PROMPT :\n{user_prompt}\n" + "="*60 + "\n")

        for i, (provider, model_key) in enumerate(fallback_chain):
            # Si on retente EXACTEMENT le même modèle que la tentative précédente,
            # on patiente 3s pour lui laisser une vraie chance de se rétablir.
            if i > 0 and fallback_chain[i - 1][1] == model_key:
                time.sleep(3.0)

            try:
                logging.info(f"[STYLE] Étape {round_num:02d}/8 -> Essai du nœud {i+1}/{len(fallback_chain)} : [{provider.upper()}] {model_key}")
                response_text = execute_style_llm_call(provider, model_key, system_prompt, user_prompt)

                if not response_text.strip():
                    raise ValueError("La réponse générée par l'IA est vide ou instable.")

                if patch_mode:
                    patches = parse_patches(response_text)

                    if patches is None:
                        # Le modèle n'a pas respecté le format patch (arrive avec les
                        # modèles bas de gamme) -> secours : on traite sa réponse comme
                        # un fichier complet UNIQUEMENT si elle ne ressemble PAS à une
                        # tentative de patch JSON cassée (sinon on corromprait tout le
                        # pipeline avec du JSON brut pris pour du HTML).
                        fallback_code = strip_code_fences(response_text)
                        stripped_fb = fallback_code.strip()
                        looks_like_broken_patch_attempt = (
                            stripped_fb.startswith("[")
                            or ('"old"' in fallback_code and '"new"' in fallback_code)
                        )
                        looks_like_code = (not looks_like_broken_patch_attempt) and any(
                            marker in fallback_code
                            for marker in ("<div", "<section", "<button", "<span", "<header", "<main", "export default")
                        )
                        if looks_like_code:
                            print(f"[PATCH SECOURS] {model_key} n'a pas renvoyé un JSON de patchs valide -> traité comme fichier complet.")
                            final_code = fallback_code
                        else:
                            print(f"[PATCH PARSING ÉCHOUÉ] Contenu brut reçu de {model_key} (premiers 1500 caractères) :\n{response_text[:1500]}\n{'...(tronqué)' if len(response_text) > 1500 else ''}")
                            raise ValueError("Réponse illisible : ni patchs JSON valides, ni code HTML/React reconnaissable (JSON de patch cassé détecté, rejeté pour éviter la corruption).")
                    elif len(patches) == 0:
                        # Cas légitime (ex: correcteur qui juge qu'il n'y a rien à corriger)
                        print(f"[PATCH] {model_key} n'a proposé aucun patch (fichier jugé propre ou rien à ajouter).")
                        final_code = context
                    else:
                        final_code, applied, failed = apply_patches(context, patches)
                        if applied == 0:
                            raise ValueError(f"Aucun des {len(patches)} patch(s) proposé(s) n'a pu être appliqué (correspondance 'old' introuvable).")
                else:
                    # Round 1 sur page vierge : le modèle renvoie le fichier complet directement.
                    final_code = strip_code_fences(response_text)

                # Nettoyage final systématique au round 8 (correcteur)
                if round_num == 8:
                    final_code = ensure_use_client_directive(final_code)

                return jsonify({
                    "response": final_code.strip(),
                    "model_used": MODELS.get(model_key, model_key),
                    "round": round_num
                })

            except Exception as node_error:
                print(f"[NODE STYLE ERROR] Échec du nœud {i+1}/{len(fallback_chain)} ({model_key}) au round {round_num} : {node_error}")
                continue

        return jsonify(ERR_FINAL)

    except Exception as general_error:
        print(f"[STYLE CRITICAL] {general_error}")
        return jsonify(ERR_CRASH), 500

@app.route("/ping")
def ping():
    return jsonify({"status": "style_engine_online"})

if __name__ == "__main__":
    print("[STYLE SERVER] Moteur de mutation créatif sur port 5002 initialisé (8 rounds, Gemini direct en round 1).")
    app.run(host="0.0.0.0", port=5002)