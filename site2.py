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
    "grok":        "xai/grok-4-1-fast-non-reasoning",
    "grok_fast":   "xai/grok-4-fast-non-reasoning",
    "qwen3":       "deepinfra/Qwen/Qwen3-235B-A22B-Instruct-2507",
    "luna":        "azure/gpt-6-luna@eastus2",
    "gemini_lite": "google/gemini-2.5-flash-lite",
}

REQUESTY_API_KEY = os.getenv("REQUESTY_API_KEY", "").strip()

client_requesty = (
    OpenAI(base_url="https://router.requesty.ai/v1", api_key=REQUESTY_API_KEY)
    if REQUESTY_API_KEY else None
)

def call_requesty(model_name: str, messages_openai, temp=0.5, timeout=20.0, max_tokens=2500):
    if client_requesty is None:
        raise RuntimeError("Requesty non configuré")
    res = client_requesty.chat.completions.create(
        model=model_name,
        messages=messages_openai,
        temperature=temp,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    content = res.choices[0].message.content
    if content is None:
        raise ValueError(f"Reponse vide de {model_name}")
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
        <a href="[https://tonsite.com/1/fiche](https://tonsite.com/1/fiche)" style="display:inline-block; background:#18181b; color:white; padding:12px 24px; border-radius:10px; text-decoration:none; font-weight:600; margin-top:12px;">
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
    from echo_api import prepare_shared_context, call_deepseek
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="chat")

        steps = [("ds", None, 20), ("rq", SITE2_MODELS["grok_fast"], 20), ("ds", None, 20)]
        for provider, model_key, timeout in steps:
            try:
                if provider == "ds":
                    raw = call_deepseek(ctx, temp=0.5, timeout=float(timeout))
                else:
                    raw = call_requesty(model_key, ctx["messages_openai"], temp=0.5,
                                         timeout=float(timeout), max_tokens=ctx.get("output_tokens", 2500))
                return jsonify(clean_and_parse_json_site2(raw))
            except Exception as e:
                tag = "deepseek" if provider == "ds" else model_key
                print(f"[SITE2 CONVERSATION] Echec {tag} ({e})")
        return jsonify(ERR_CRASH)
    except Exception as e:
        print(f"Erreur /1/conversation: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/generate-invoice ───────────────────────────────────────────────────────
@site2_bp.route("/1/generate-invoice", methods=["POST"])
def generate_invoice():
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
                raw = call_requesty(SITE2_MODELS["luna"], messages, temp=0.2, timeout=20.0, max_tokens=800)
                print("[INVOICE] Luna OK")
            except Exception as e:
                print(f"[INVOICE] Luna echec ({e})")
            
            if not raw:
                try:
                    raw = call_requesty(SITE2_MODELS["grok_fast"], messages, temp=0.2, timeout=20.0, max_tokens=800)
                    print("[INVOICE] Grok OK")
                except Exception as e:
                    print(f"[INVOICE] Grok echec ({e})")

        if not raw:
            from echo_api import client_deepseek, MODELS
            if client_deepseek is not None:
                try:
                    res = client_deepseek.chat.completions.create(
                        model=MODELS.get("deepseek", "deepseek-flash"),
                        messages=messages,
                        temperature=0.2,
                        max_tokens=800,
                        timeout=25.0
                    )
                    raw = res.choices[0].message.content
                    print("[INVOICE] DeepSeek OK")
                except Exception as e:
                    print(f"[INVOICE] DeepSeek echec ({e})")

        if not raw:
            return jsonify({"error": "IA indisponible"}), 503

        import json
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
                    model=SITE2_MODELS["grok_fast"], messages=messages,
                    temperature=0.3, max_tokens=1200, timeout=20.0)
                raw = (res.choices[0].message.content or "").strip() or None
                if raw: print("[IDEA] Grok-Fast OK")
            except Exception as e:
                print(f"[IDEA] Grok-Fast echec ({e})")

            if not raw:
                try:
                    res = client_requesty.chat.completions.create(
                        model=SITE2_MODELS["luna"], messages=messages,
                        temperature=0.3, max_tokens=1200, timeout=20.0)
                    raw = (res.choices[0].message.content or "").strip() or None
                    if raw: print("[IDEA] Luna OK")
                except Exception as e:
                    print(f"[IDEA] Luna echec ({e})")

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
    # ── Amérique du Nord (xAI / OpenAI)
    "na_1": "xai/grok-4-fast-non-reasoning",
    "na_2": "openai/gpt-6-luna",

    # ── Chine / Asie (DeepSeek / Qwen Alibaba / Zhipu GLM)
    "cn_1": "deepseek-flash",
    "cn_2": "deepinfra/Qwen/Qwen3-235B-A22B-Instruct-2507",
    "cn_3": "thudm/glm-4-9b-chat",

    # ── Europe (Mistral AI - France)
    "eu_1": "mistral/mistral-small-latest",
    "eu_2": "mistral/mistral-large-latest",
    "eu_3": "mistral/mistral-small-2603",
}

def _strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*',     r'\1', text)
    text = re.sub(r'#{1,6}\s*',       '',    text)
    text = re.sub(r'`([^`]+)`',       r'\1', text)
    return text.strip()

def _clean_cut(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_end = -1
    for punct in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
        pos = truncated.rfind(punct)
        if pos > last_end:
            last_end = pos
    if last_end > max_chars // 2:
        return truncated[:last_end + 1].strip()
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        return truncated[:last_space].strip() + "\u2026"
    return truncated.strip() + "\u2026"

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
    content       = choice.message.content
    if content is None:
        raise ValueError(f"Réponse None de {model_name} ({finish_reason})")
    content = content.strip()
    if not content:
        raise ValueError(f"Réponse vide de {model_name} ({finish_reason})")
    return _clean_cut(_strip_markdown(content), 650)

def run_world_cascade(continent: str, messages: list, attempt: int = 0) -> str:
    from echo_api import client_deepseek

    steps = {
        "na": [
            (client_requesty, WORLD_MODELS["na_1"], 20.0),
            (client_requesty, WORLD_MODELS["na_2"], 20.0),
            (client_requesty, WORLD_MODELS["na_1"], 20.0),
        ],
        "cn": [
            (client_deepseek, WORLD_MODELS["cn_1"], 30.0),
            (client_requesty, WORLD_MODELS["cn_2"], 30.0),
            (client_requesty, WORLD_MODELS["cn_3"], 20.0),
        ],
        "eu": [
            (client_requesty, WORLD_MODELS["eu_1"], 20.0),
            (client_requesty, WORLD_MODELS["eu_2"], 20.0),
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
        time.sleep(1.0)
        return run_world_cascade(continent, messages, attempt + 1)

    return "Service temporairement indisponible pour ce continent."

@site2_bp.route("/world/warmup", methods=["POST"])
def world_warmup():
    return jsonify({"status": "ready"}), 200

@site2_bp.route("/world/conversation", methods=["POST"])
def world_conversation():
    try:
        from prompts_world import get_world_system_prompt, get_world_user_prompt
        data      = request.json or {}

        if data.get("warmup"):
            return jsonify({"status": "warm"}), 200

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


# ══════════════════════════════════════════════════════════════════════════════
# ── SECTION SOLUTION — TRIPLE CASCADE PARALLÈLE AVEC RECHERCHE WEB EN DIRECT ──
# ══════════════════════════════════════════════════════════════════════════════
from concurrent.futures import ThreadPoolExecutor

MODEL_LUNA_PRIMARY = "openai/gpt-6-luna"
MODEL_LUNA_AZURE   = "azure/gpt-6-luna@eastus2"
MODEL_GEMINI_LITE  = "google/gemini-2.5-flash-lite"
MODEL_GROK         = "xai/grok-4-fast-non-reasoning"
MODEL_DEEPSEEK     = "deepseek-flash"

def _call_single_model(client, model_name: str, messages: list, timeout: float = 35.0, temp: float = 0.4, enable_web: bool = False) -> str:
    """Appel d'un modèle avec activation de la recherche web en direct si demandée."""
    if client is None:
        raise RuntimeError(f"Client non disponible pour {model_name}")
    
    kwargs = {
        "model": model_name,
        "messages": messages,
        "temperature": temp,
        "max_tokens": 20000,
        "timeout": timeout,
    }

    # Activation de la recherche web en direct pour Requesty et OpenRouter
    if enable_web:
        base_url = str(getattr(client, "base_url", ""))
        if "requesty" in base_url or "openrouter" in base_url:
            kwargs["extra_body"] = {"plugins": [{"id": "web"}]}

    res = client.chat.completions.create(**kwargs)
    content = res.choices[0].message.content
    if not content or not content.strip():
        raise ValueError(f"Contenu vide retourné par {model_name}")
    return content.strip()

# ── 1. CASCADE IA HAUT-GAUCHE : SOURCES FIABLES & DOCUMENTATION (WEB ACTIF) ──
# Ordre : Luna Direct -> Luna Azure -> Gemini 2.5 Flash Lite -> Grok
def execute_doc_cascade(question: str, lang: str = "fr") -> str:
    from prompts_solution import get_solution_system_prompt, get_solution_user_prompt
    from echo_api import client_openrouter

    messages = [
        {"role": "system", "content": get_solution_system_prompt("doc", lang)},
        {"role": "user",   "content": get_solution_user_prompt("doc", question, lang=lang)}
    ]

    steps = [
        ("Requesty-Luna", client_requesty, MODEL_LUNA_PRIMARY, 25.0),
        ("Requesty-Azure", client_requesty, MODEL_LUNA_AZURE, 25.0),
        ("Requesty/OR", client_requesty or client_openrouter, MODEL_GEMINI_LITE, 20.0),
        ("Requesty", client_requesty, MODEL_GROK, 20.0),
    ]

    for name, client, model_name, timeout in steps:
        try:
            out = _call_single_model(client, model_name, messages, timeout=timeout, temp=0.2, enable_web=True)
            print(f"[SOLUTION][DOCS-WEB] {model_name} OK")
            return out
        except Exception as e:
            print(f"[SOLUTION][DOCS-WEB] Échec {model_name} ({e})")

    return "Impossible de récupérer les documentations officielles pour le moment."

# ── 2. CASCADE IA HAUT-DROITE : FORUMS & RÉALITÉ DU TERRAIN (WEB ACTIF) ──────
# Ordre : DeepSeek (timeout adapté) -> Luna Direct -> Luna Azure -> Gemini Lite
def execute_forum_cascade(question: str, lang: str = "fr") -> str:
    from prompts_solution import get_solution_system_prompt, get_solution_user_prompt
    from echo_api import client_deepseek, client_openrouter

    messages = [
        {"role": "system", "content": get_solution_system_prompt("forum", lang)},
        {"role": "user",   "content": get_solution_user_prompt("forum", question, lang=lang)}
    ]

    steps = [
        ("DeepSeek", client_deepseek, MODEL_DEEPSEEK, 45.0),  # 👈 45s pour laisser le temps de chercher
        ("Requesty-Luna", client_requesty, MODEL_LUNA_PRIMARY, 25.0),
        ("Requesty-Azure", client_requesty, MODEL_LUNA_AZURE, 25.0),
        ("Requesty/OR", client_requesty or client_openrouter, MODEL_GEMINI_LITE, 20.0),
    ]

    for name, client, model_name, timeout in steps:
        try:
            out = _call_single_model(client, model_name, messages, timeout=timeout, temp=0.4, enable_web=True)
            print(f"[SOLUTION][FORUM-WEB] {model_name} OK")
            return out
        except Exception as e:
            print(f"[SOLUTION][FORUM-WEB] Échec {model_name} ({e})")

    return "Aucun contournement du terrain détecté sur les forums pour le moment."

# ── 3. CASCADE IA DU BAS : ARBITRE SANS FILTRE & PLAN D'ACTION CASH ──────────
# Ordre : DeepSeek (45s pour bien digérer les 2 sources) -> Luna Direct -> Luna Azure -> Grok
def execute_arbiter_cascade(question: str, doc_text: str, forum_text: str, lang: str = "fr") -> str:
    from prompts_solution import get_solution_system_prompt, get_solution_user_prompt
    from echo_api import client_deepseek

    messages = [
        {"role": "system", "content": get_solution_system_prompt("arbiter", lang)},
        {"role": "user",   "content": get_solution_user_prompt("arbiter", question, doc_text=doc_text, forum_text=forum_text, lang=lang)}
    ]

    steps = [
        ("DeepSeek", client_deepseek, MODEL_DEEPSEEK, 45.0),  # 👈 Timeout confortable pour la synthèse complète
        ("Requesty-Luna", client_requesty, MODEL_LUNA_PRIMARY, 25.0),
        ("Requesty-Azure", client_requesty, MODEL_LUNA_AZURE, 25.0),
        ("Requesty", client_requesty, MODEL_GROK, 25.0),
    ]

    for name, client, model_name, timeout in steps:
        try:
            out = _call_single_model(client, model_name, messages, timeout=timeout, temp=0.3, enable_web=False)
            print(f"[SOLUTION][ARBITRE] {model_name} OK")
            return out
        except Exception as e:
            print(f"[SOLUTION][ARBITRE] Échec {model_name} ({e})")

    return "Arbitrage impossible suite à une indisponibilité technique temporaire."

# ── ROUTE HTTP PRINCIPALE SOLUTION (PARALLÉLISÉE) ─────────────────────────────
@site2_bp.route("/solution/resolve", methods=["POST"])
@site2_bp.route("/api/solution/resolve", methods=["POST"])
def solution_resolve():
    """
    Exécute Doc et Forum SIMULTANÉMENT via un pool de threads,
    puis envoie les deux résultats consolidés à l'Arbitre.
    """
    try:
        data     = request.json or {}
        question = (data.get("question") or "").strip()
        lang     = (data.get("lang") or "fr").strip().lower()

        if not question:
            return jsonify({"error": "Question requise"}), 400

        print(f"[SOLUTION] Lancement parallèle pour : {question[:60]}...")

        # 1. Parallélisation : Doc et Forum tournent en même temps
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_doc   = executor.submit(execute_doc_cascade, question, lang)
            future_forum = executor.submit(execute_forum_cascade, question, lang)

            doc_result   = future_doc.result()
            forum_result = future_forum.result()

        # 2. Arbitrage : prend le relais dès que les deux threads sont complétés
        final_solution = execute_arbiter_cascade(question, doc_result, forum_result, lang=lang)

        return jsonify({
            "docResponse": doc_result,
            "forumResponse": forum_result,
            "finalSolution": final_solution,
        }), 200

    except Exception as e:
        print(f"[SOLUTION] Erreur générale: {e}")
        return jsonify({
            "docResponse": "Erreur lors de l'analyse documentaire.",
            "forumResponse": "Erreur lors de l'analyse des forums.",
            "finalSolution": f"Une erreur interne est survenue : {str(e)}",
        }), 500