from flask import Blueprint, request, jsonify
import os
import re
import time
import resend
from openai import OpenAI


site2_bp = Blueprint("site2", __name__)

ERR_CRASH = {"action": None, "response": "Une erreur inattendue s'est produite. Reessaie dans quelques secondes."}

resend.api_key = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "Echo AI <support@echosai.ca>")

# ── RATE LIMIT récupération Key — 2x/heure max par email ─────────────────────
_recovery_attempts = {}

def check_recovery_rate_limit(email: str) -> bool:
    now = time.time()
    attempts = _recovery_attempts.get(email, [])
    attempts = [t for t in attempts if now - t < 3600]
    if len(attempts) >= 2:
        return False
    attempts.append(now)
    _recovery_attempts[email] = attempts
    return True

# ── MODÈLES SITE2 ─────────────────────────────────────────────────────────────
SITE2_MODELS = {
    "grok":  "xai/grok-4-1-fast-non-reasoning",
    "qwen3": "deepinfra/Qwen/Qwen3-235B-A22B-Instruct-2507",
}

REQUESTY_API_KEY = os.getenv("REQUESTY_API_KEY", "").strip()

client_requesty = (
    OpenAI(base_url="https://router.requesty.ai/v1", api_key=REQUESTY_API_KEY)
    if REQUESTY_API_KEY else None
)

def call_requesty(model_key: str, messages_openai, temp=0.5, timeout=20.0, max_tokens=2500):
    if client_requesty is None:
        raise RuntimeError("Requesty non configuré")
    res = client_requesty.chat.completions.create(
        model=SITE2_MODELS[model_key],
        messages=messages_openai,
        temperature=temp,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    content = res.choices[0].message.content
    if content is None:
        raise ValueError(f"Reponse vide de {model_key}")
    return content

# ── PARSER JSON ───────────────────────────────────────────────────────────────
def clean_and_parse_json_site2(raw_text):
    import json
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
            if isinstance(parsed["response"], str):
                parsed["response"] = parsed["response"].replace("\\n", "\n").replace("\\\\n", "\n")
            return parsed
    except Exception:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and "response" in parsed:
                if isinstance(parsed["response"], str):
                    parsed["response"] = parsed["response"].replace("\\n", "\n").replace("\\\\n", "\n")
                return parsed
        except Exception:
            pass
    if '"response":' in text:
        res_match = re.search(r'"response"\s*:\s*"([^"]+)"', text)
        if res_match:
            response_text = res_match.group(1).replace("\\n", "\n").replace("\\\\n", "\n")
            return {"action": None, "response": response_text}
    return {"action": None, "response": text}

# ── ENVOYER LA KEY PAR COURRIEL ──────────────────────────────────────────────
def send_key_email(to_email: str, key: str, is_recovery: bool = False):
    subject = "Ta clé Echo AI 🔑" if not is_recovery else "Récupération de ta clé Echo AI"
    html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
        <h2>{"Bienvenue sur Echo AI !" if not is_recovery else "Voici ta clé"}</h2>
        <p>{"Ta fiche est en ligne. Voici ta clé personnelle :" if not is_recovery else "Tu as demandé à récupérer ta clé personnelle :"}</p>
        <div style="background: #18181b; color: white; padding: 20px; border-radius: 12px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 1px; margin: 20px 0;">
            {key}
        </div>
        <p style="color: #ef4444; font-size: 13px; font-weight: 600;">⚠️ Conserve précieusement cette clé — c'est ton identité unique sur la plateforme et le seul moyen de débloquer les fiches que tu achètes.</p>
        <p style="color: #71717a; font-size: 12px;">Tu peux la redemander jusqu'à 2 fois par heure si besoin.</p>
    </div>
    """
    try:
        resend.Emails.send({"from": RESEND_FROM, "to": [to_email], "subject": subject, "html": html})
        return True
    except Exception as e:
        print(f"[RESEND] Erreur envoi: {e}")
        return False

# ── NOTIFICATION D'INTÉRÊT ────────────────────────────────────────────────────
def send_interet_email(to_email: str, fiche_nom: str, sender_key: str, type_interet: str):
    is_fort = type_interet == "tres_interesse"
    subject = f"{sender_key} est très intéressé par votre fiche ! 🔥" if is_fort else f"{sender_key} a de l'intérêt pour votre fiche 💌"
    label   = "est très intéressé" if is_fort else "a de l'intérêt"
    emoji   = "🔥" if is_fort else "💌"
    html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
        <h2>{emoji} Nouvelle activité sur ta fiche</h2>
        <p><strong>{sender_key}</strong> {label} pour <strong>{fiche_nom}</strong>.</p>
        <a href="https://tonsite.com/1/fiche" style="display:inline-block; background:#18181b; color:white; padding:12px 24px; border-radius:10px; text-decoration:none; font-weight:600; margin-top:12px;">
            Voir qui s'intéresse à ta fiche →
        </a>
    </div>
    """
    try:
        resend.Emails.send({"from": RESEND_FROM, "to": [to_email], "subject": subject, "html": html})
        return True
    except Exception as e:
        print(f"[RESEND] Erreur envoi interet: {e}")
        return False

# ── /1/envoyer-cle ────────────────────────────────────────────────────────────
@site2_bp.route("/1/envoyer-cle", methods=["POST"])
def envoyer_cle():
    try:
        data  = request.json or {}
        email = (data.get("email") or "").strip()
        key   = (data.get("key")   or "").strip()
        if not email or not key:
            return jsonify({"error": "Email et clé requis"}), 400
        ok = send_key_email(email, key, is_recovery=False)
        return jsonify({"sent": ok})
    except Exception as e:
        print(f"Erreur /1/envoyer-cle: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/recuperer-cle ──────────────────────────────────────────────────────────
@site2_bp.route("/1/recuperer-cle", methods=["POST"])
def recuperer_cle():
    try:
        import os, requests as req
        data  = request.json or {}
        email = (data.get("email") or "").strip()
        if not email:
            return jsonify({"error": "Email requis"}), 400
        if not check_recovery_rate_limit(email):
            return jsonify({"error": "rate_limited", "message": "Trop de demandes. Réessaie dans une heure."}), 429
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        res = req.get(
            f"{supabase_url}/rest/v1/fiches",
            params={"email_prive": f"eq.{email}", "select": "key"},
            headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"},
        )
        rows = res.json() if res.ok else []
        if not rows:
            return jsonify({"sent": True})
        key = rows[0]["key"]
        send_key_email(email, key, is_recovery=True)
        return jsonify({"sent": True})
    except Exception as e:
        print(f"Erreur /1/recuperer-cle: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/notifier-interet ───────────────────────────────────────────────────────
@site2_bp.route("/1/notifier-interet", methods=["POST"])
def notifier_interet():
    try:
        import os, requests as req
        data         = request.json or {}
        fiche_id     = (data.get("fiche_id")   or "").strip()
        sender_key   = (data.get("sender_key") or "Quelqu'un").strip()
        type_interet = (data.get("type")       or "like").strip()
        if not fiche_id:
            return jsonify({"error": "fiche_id requis"}), 400
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
        res = req.get(
            f"{supabase_url}/rest/v1/fiches",
            params={"id": f"eq.{fiche_id}", "select": "nom_projet,email_prive,likes,interets"},
            headers=headers,
        )
        rows = res.json() if res.ok else []
        if not rows:
            return jsonify({"error": "Fiche introuvable"}), 404
        fiche = rows[0]
        field     = "interets" if type_interet == "tres_interesse" else "likes"
        new_count = (fiche.get(field) or 0) + 1
        req.patch(f"{supabase_url}/rest/v1/fiches", params={"id": f"eq.{fiche_id}"},
                  headers={**headers, "Content-Type": "application/json"}, json={field: new_count})
        req.post(f"{supabase_url}/rest/v1/fiche_interets",
                 headers={**headers, "Content-Type": "application/json"},
                 json={"fiche_id": fiche_id, "sender_key": sender_key, "type": type_interet})
        if fiche.get("email_prive"):
            send_interet_email(fiche["email_prive"], fiche["nom_projet"], sender_key, type_interet)
        return jsonify({"ok": True, "new_count": new_count})
    except Exception as e:
        print(f"Erreur /1/notifier-interet: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/conversation ───────────────────────────────────────────────────────────
@site2_bp.route("/1/conversation", methods=["POST"])
def site2_conversation():
    from echo_api import prepare_shared_context, run_paid_cascade, run_free_cascade, is_paid_tier
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="chat")
        if client_requesty is not None:
            for model_key in ("grok", "qwen3"):
                try:
                    raw    = call_requesty(model_key, ctx["messages_openai"], temp=0.5, timeout=20.0, max_tokens=ctx.get("output_tokens", 2500))
                    result = clean_and_parse_json_site2(raw)
                    return jsonify(result)
                except Exception as e:
                    print(f"[SITE2] {model_key}/Requesty echec ({e})")
        if is_paid_tier(ctx["user_tier"]):
            return jsonify(run_paid_cascade(ctx, page_timeout=15))
        steps = [("ds", "deepseek", 8), ("z", "glm", 15), ("or", "llama", 12)]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /1/conversation: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/generate-invoice ───────────────────────────────────────────────────────
@site2_bp.route("/1/generate-invoice", methods=["POST"])
def generate_invoice():
    from echo_api import client_zai, MODELS
    import json

    try:
        data      = request.json or {}
        free_text = (data.get("freeText") or "").strip()
        currency  = (data.get("currency") or "CAD").strip()
        status    = (data.get("status")   or "pending").strip()
        lang      = (data.get("lang")     or "fr").strip()
        numero    = (data.get("numero")   or "INV-001").strip()
        date_str  = (data.get("dateStr")  or "").strip()
        due_str   = (data.get("dueStr")   or "").strip()
        if not free_text:
            return jsonify({"error": "Texte requis"}), 400
        lang_instr   = "Reponds en francais." if lang == "fr" else "Answer in English."
        status_map   = {"pending": "En attente" if lang == "fr" else "Pending",
                        "paid":    "Payee"      if lang == "fr" else "Paid",
                        "late":    "En retard"  if lang == "fr" else "Overdue"}
        status_label = status_map.get(status, "En attente")
        system_prompt = (
            "Tu es un expert en facturation professionnelle. "
            "Extrais TOUTES les informations du texte et retourne un JSON complet. "
            "Regles: 1. EMETTEUR = premiere entreprise/personne. 2. CLIENT = deuxieme. "
            "3. Extrait adresse, email, telephone. 4. EMAIL = tout ce qui contient @. "
            "5. TELEPHONE = tout numero. 6. MONTANT = additionne tous. "
            "7. Reformule la description. 8. Genere conditions de paiement. "
            + lang_instr + " Reponds UNIQUEMENT avec ce JSON: "
            '{"emetteur":"","adresseEmetteur":"","emailEmetteur":"","telEmetteur":"",'
            '"neq":"","numTPS":"","numTVQ":"","client":"","adresseClient":"","telClient":"",'
            '"emailClient":"","description":"","montantHT":0.00,"conditions":"","notes":""}'
        )
        user_prompt = (
            f"Informations:\n\n{free_text}\n\n---\nDevise: {currency}\nStatut: {status_label}\n"
            f"Numero: {numero}\nDate: {date_str}\nEcheance: {due_str}\n\nJSON uniquement."
        )
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        raw = None
        if client_requesty is not None:
            try:
                raw = call_requesty("grok", messages, temp=0.2, timeout=25.0, max_tokens=800)
                print("[INVOICE] Grok OK")
            except Exception as e:
                print(f"[INVOICE] Grok echec ({e})")
        if not raw and client_requesty is not None:
            try:
                raw = call_requesty("qwen3", messages, temp=0.2, timeout=25.0, max_tokens=800)
                print("[INVOICE] Qwen OK")
            except Exception as e:
                print(f"[INVOICE] Qwen echec ({e})")
        if not raw:
            from echo_api import client_deepseek, MODELS
            if client_deepseek is not None:
                try:
                    res = client_deepseek.chat.completions.create(
                        model=MODELS["deepseek"], messages=messages, temperature=0.2, max_tokens=800, timeout=25.0)
                    raw = res.choices[0].message.content
                    print("[INVOICE] DeepSeek OK")
                except Exception as e:
                    print(f"[INVOICE] DeepSeek echec ({e})")
        if not raw:
            return jsonify({"error": "IA indisponible"}), 503
        text = raw.strip()
        if text.startswith("```json"): text = text[7:]
        elif text.startswith("```"):   text = text[3:]
        if text.endswith("```"):       text = text[:-3]
        text = text.strip()
        parsed = {}
        try:
            parsed = json.loads(text)
        except Exception:
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                try: parsed = json.loads(m.group(0))
                except Exception: pass
        return jsonify({
            "emetteur": parsed.get("emetteur") or "", "adresseEmetteur": parsed.get("adresseEmetteur") or "",
            "emailEmetteur": parsed.get("emailEmetteur") or "", "telEmetteur": parsed.get("telEmetteur") or "",
            "neq": parsed.get("neq") or "", "numTPS": parsed.get("numTPS") or "", "numTVQ": parsed.get("numTVQ") or "",
            "client": parsed.get("client") or "", "adresseClient": parsed.get("adresseClient") or "",
            "telClient": parsed.get("telClient") or "", "emailClient": parsed.get("emailClient") or "",
            "description": parsed.get("description") or "", "montantHT": parsed.get("montantHT") or 0,
            "conditions": parsed.get("conditions") or "", "notes": parsed.get("notes") or "",
        })
    except Exception as e:
        print(f"[INVOICE] Erreur: {e}")
        return jsonify({"error": str(e)}), 500

# ── /2/analyse-idee ───────────────────────────────────────────────────────────
@site2_bp.route("/2/analyse-idee", methods=["POST"])
def analyse_idee():
    from echo_api import client_deepseek, client_gemini_paid, client_zai, MODELS
    from google.genai import types as gtypes
    from prompts2 import get_idea_system_prompt, get_idea_user_prompt
    import json

    try:
        data = request.json or {}
        idea = (data.get("idea") or "").strip()
        lang = (data.get("lang") or "fr").strip()
        if not idea or len(idea) < 10:
            return jsonify({"error": "Idée trop courte"}), 400
        system_prompt = get_idea_system_prompt(lang)
        user_prompt   = get_idea_user_prompt(idea, lang)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        raw = None
        if client_requesty is not None:
            try:
                res = client_requesty.chat.completions.create(
                    model="xai/grok-4-fast-non-reasoning", messages=messages, temperature=0.3, max_tokens=1200, timeout=25.0)
                raw = (res.choices[0].message.content or "").strip() or None
                if raw: print("[IDEA] Grok-4-fast-non-reasoning OK")
            except Exception as e:
                print(f"[IDEA] Grok echec ({e})")
        if not raw and client_gemini_paid is not None:
            try:
                r = client_gemini_paid.models.generate_content(
                    model=MODELS["gemini_paid_ultra"],
                    contents=[{"role": "user", "parts": [gtypes.Part.from_text(text=user_prompt)]}],
                    config=gtypes.GenerateContentConfig(system_instruction=system_prompt, max_output_tokens=1200, temperature=0.3))
                raw = (r.text or "").strip() or None
                if raw: print("[IDEA] Gemini OK")
            except Exception as e:
                print(f"[IDEA] Gemini echec ({e})")
        if not raw and client_requesty is not None:
            try:
                res = client_requesty.chat.completions.create(
                    model="xai/grok-4-fast", messages=messages, temperature=0.3, max_tokens=1200, timeout=25.0)
                raw = (res.choices[0].message.content or "").strip() or None
                if raw: print("[IDEA] Grok-4-fast OK")
            except Exception as e:
                print(f"[IDEA] Grok-4-fast echec ({e})")
        if not raw:
            return jsonify({"error": "Analyse indisponible"}), 503
        text = raw.strip()
        if text.startswith("```json"): text = text[7:]
        elif text.startswith("```"):   text = text[3:]
        if text.endswith("```"):       text = text[:-3]
        text = text.strip()
        parsed = {}
        try:
            parsed = json.loads(text)
        except Exception:
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                try: parsed = json.loads(m.group(0))
                except Exception: pass
        if not parsed:
            return jsonify({"error": "Réponse non parseable"}), 500
        return jsonify(parsed)
    except Exception as e:
        print(f"[IDEA] Erreur: {e}")
        return jsonify({"error": str(e)}), 500

# ── /1/supprimer-fiche ────────────────────────────────────────────────────────
@site2_bp.route("/1/supprimer-fiche", methods=["POST"])
def supprimer_fiche():
    try:
        import os, requests as req
        data  = request.json or {}
        key   = (data.get("key")   or "").strip()
        email = (data.get("email") or "").strip()
        if not key or not email:
            return jsonify({"error": "Clé et courriel requis"}), 400
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
        res = req.get(f"{supabase_url}/rest/v1/fiches",
                      params={"key": f"eq.{key}", "email_prive": f"eq.{email}", "select": "id"}, headers=headers)
        rows = res.json() if res.ok else []
        if not rows:
            return jsonify({"error": "Clé ou courriel incorrect."}), 403
        fiche_id = rows[0]["id"]
        del_res  = req.delete(f"{supabase_url}/rest/v1/fiches", params={"id": f"eq.{fiche_id}"}, headers=headers)
        if not del_res.ok:
            return jsonify({"error": "Échec de la suppression."}), 500
        return jsonify({"deleted": True})
    except Exception as e:
        print(f"Erreur /1/supprimer-fiche: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/check-unlock ───────────────────────────────────────────────────────────
@site2_bp.route("/1/check-unlock", methods=["POST"])
def check_unlock():
    try:
        import requests as req
        data        = request.json or {}
        fiche_id    = (data.get("fiche_id")    or "").strip()
        acheteur_id = (data.get("acheteur_id") or "").strip()
        if not fiche_id or not acheteur_id:
            return jsonify({"unlocked": False})
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
        res  = req.get(f"{supabase_url}/rest/v1/tunnels",
                       params={"fiche_id": f"eq.{fiche_id}", "acheteur_id": f"eq.{acheteur_id}", "select": "id"},
                       headers=headers)
        rows = res.json() if res.ok else []
        return jsonify({"unlocked": len(rows) > 0})
    except Exception as e:
        print(f"Erreur /1/check-unlock: {e}")
        return jsonify({"unlocked": False})


# ══════════════════════════════════════════════════════════════════════════════
# ── WORLD — CASCADE 3 CONTINENTS ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

WORLD_MODELS = {
    "na_1": "xai/grok-4-fast-non-reasoning",    # Requesty
    "na_2": "gemini-3.1-flash-lite",             # Requesty
    "na_3": "openai/gpt-4o-mini-search-preview", # OpenRouter
    "cn_1": "deepseek-v4-flash",                 # DeepSeek direct
    "cn_2": "GLM-4.7-Flash",                      # Z.AI direct
    "cn_3": "deepinfra/Qwen/Qwen3-235B-A22B-Instruct-2507", # Requesty/DeepInfra
    "eu_1": "mistral/mistral-small-latest",      # Requesty
    "eu_2": "mistralai/mistral-small-2603",      # OpenRouter
    "eu_3": "mistral/mistral-small-2603",        # Requesty
}

def _strip_markdown(text: str) -> str:
    """FIX 3 — retire le markdown que certains modèles insèrent malgré l'instruction."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*',     r'\1', text)
    text = re.sub(r'#{1,6}\s*',       '',    text)
    text = re.sub(r'`([^`]+)`',       r'\1', text)
    return text.strip()

def call_world_model(client, model_name: str, messages: list, timeout: float = 20.0) -> str:
    if client is None:
        raise RuntimeError(f"Client non configuré pour {model_name}")
    res = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0.5,
        max_tokens=1200,
        timeout=timeout,
    )
    choice        = res.choices[0]
    finish_reason = getattr(choice, "finish_reason", "unknown")
    message       = choice.message
    content       = message.content

    # DEBUG complet — log finish_reason + model_dump pour trouver où GLM cache sa réponse
    print(f"[WORLD DEBUG] {model_name} | finish_reason={finish_reason} | content_len={len(content) if content else 0}")

    # Si contenu vide — chercher dans tous les champs alternatifs (GLM, DeepSeek, Z.AI)
    if not content:
        try:
            raw_dump = message.model_dump()
            print(f"[WORLD DEBUG] {model_name} model_dump = {raw_dump}")
        except Exception as dump_err:
            print(f"[WORLD DEBUG] model_dump error: {dump_err}")

        # Champs alternatifs connus: reasoning_content, reasoning, thinking
        for field in ("reasoning_content", "reasoning", "thinking"):
            alt = getattr(message, field, None)
            if alt and str(alt).strip():
                print(f"[WORLD DEBUG] {model_name} — contenu trouvé dans {field}!")
                content = str(alt)
                break

    if content is None:
        raise ValueError(f"Réponse None de {model_name} (finish_reason={finish_reason})")
    content = content.strip()
    if not content:
        raise ValueError(f"Réponse vide de {model_name} (finish_reason={finish_reason})")
    return _strip_markdown(content)[:672]

def run_world_cascade(continent: str, messages: list, attempt: int = 0) -> str:
    from echo_api import client_deepseek, client_zai
    try:
        from echo_api import client_openrouter as _client_or
    except ImportError:
        _client_or = None

    steps = {
        "na": [
            (client_requesty, WORLD_MODELS["na_1"], 20.0),
            (client_requesty, WORLD_MODELS["na_2"], 20.0),
            (_client_or,      WORLD_MODELS["na_3"], 25.0),
        ],
        "cn": [
            (client_deepseek, WORLD_MODELS["cn_1"], 60.0),
            (client_zai,      WORLD_MODELS["cn_2"], 60.0),
            (client_requesty, WORLD_MODELS["cn_3"], 60.0),  # Qwen3-235B fallback
        ],
        "eu": [
            (client_requesty, WORLD_MODELS["eu_1"], 20.0),
            (_client_or,      WORLD_MODELS["eu_2"], 20.0),
            (client_requesty, WORLD_MODELS["eu_3"], 20.0),
        ],
    }.get(continent, [])

    for client, model_name, timeout in steps:
        try:
            result = call_world_model(client, model_name, messages, timeout)
            print(f"[WORLD][{continent.upper()}] {model_name} OK")
            return result
        except Exception as e:
            print(f"[WORLD][{continent.upper()}] {model_name} échec ({e})")

    if attempt < 1:
        print(f"[WORLD][{continent.upper()}] Retry complet...")
        time.sleep(1.0)
        return run_world_cascade(continent, messages, attempt + 1)

    return "Service temporairement indisponible pour ce continent."

# ── /world/conversation ───────────────────────────────────────────────────────
@site2_bp.route("/world/conversation", methods=["POST"])
def world_conversation():
    try:
        from prompts_world import get_world_system_prompt, get_world_user_prompt

        data      = request.json or {}
        question  = (data.get("question")  or "").strip()
        continent = (data.get("continent") or "eu").strip().lower()
        lang      = (data.get("lang")      or "fr").strip().lower()
        context   = (data.get("context")   or "").strip()
        is_final  = bool(data.get("isFinal", False))
        round_num = int(data.get("round",    1))
        max_chars = int(data.get("maxChars", 420))

        if not question:
            return jsonify({"error": "Question vide"}), 400
        if continent not in ("na", "cn", "eu"):
            continent = "eu"
        if lang not in ("fr", "en", "zh"):
            lang = "fr"

        # FIX 2 — tronquer le contexte pour éviter les réponses vides sur contexte trop long
        if len(context) > 900:
            context = context[-900:]

        system_prompt = get_world_system_prompt(continent, lang)
        user_prompt   = get_world_user_prompt(
            question=question,
            continent=continent,
            lang=lang,
            context=context,
            round_num=round_num,
            is_final=is_final,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]

        response_text = run_world_cascade(continent, messages)
        return jsonify({"response": response_text[:max_chars]})

    except Exception as e:
        print(f"[WORLD] Erreur critique: {e}")
        return jsonify(ERR_CRASH), 500