from flask import Blueprint, request, jsonify
import os
import time
import resend
from openai import OpenAI

site2_bp = Blueprint("site2", __name__)

ERR_CRASH = {"action": None, "response": "Une erreur inattendue s'est produite. Reessaie dans quelques secondes."}

resend.api_key = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "Echo AI <support@echosai.ca>")

# ── RATE LIMIT récupération Key — 2x/heure max par email ─────────────────────
_recovery_attempts = {}  # { email: [timestamp1, timestamp2, ...] }

def check_recovery_rate_limit(email: str) -> bool:
    now = time.time()
    attempts = _recovery_attempts.get(email, [])
    # Garder seulement les tentatives de la dernière heure
    attempts = [t for t in attempts if now - t < 3600]
    if len(attempts) >= 2:
        return False
    attempts.append(now)
    _recovery_attempts[email] = attempts
    return True

# ── MODÈLES SITE2 — propre cascade, indépendante d'Echo ─────────────────────────
SITE2_MODELS = {
    "grok":  "xai/grok-4-fast-non-reasoning",
    "qwen3": "qwen/qwen3-235b-a22b-instruct-2507",
}

REQUESTY_API_KEY = os.getenv("REQUESTY_API_KEY", "").strip()

client_requesty = (
    OpenAI(base_url="https://router.requesty.ai/v1", api_key=REQUESTY_API_KEY)
    if REQUESTY_API_KEY else None
)

def call_requesty(model_key: str, messages_openai, temp=0.5, timeout=20.0, max_tokens=2500):
    """Appel Requesty — OpenAI-compatible."""
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

# ── PARSER JSON AVEC NETTOYAGE DES \n ────────────────────────────────────────
def clean_and_parse_json_site2(raw_text):
    """Parser JSON unifié pour site2 — identique à echo_api.py"""
    import json
    import re
    
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
            # Nettoyer les \n littéraux dans la réponse
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
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
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
        resend.Emails.send({
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
        return True
    except Exception as e:
        print(f"[RESEND] Erreur envoi interet: {e}")
        return False

# ── /1/envoyer-cle (à la création de fiche) ──────────────────────────────────
@site2_bp.route("/1/envoyer-cle", methods=["POST"])
def envoyer_cle():
    try:
        data = request.json or {}
        email = (data.get("email") or "").strip()
        key   = (data.get("key") or "").strip()
        if not email or not key:
            return jsonify({"error": "Email et clé requis"}), 400
        ok = send_key_email(email, key, is_recovery=False)
        return jsonify({"sent": ok})
    except Exception as e:
        print(f"Erreur /1/envoyer-cle: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/recuperer-cle — rate limited 2x/heure ─────────────────────────────────
@site2_bp.route("/1/recuperer-cle", methods=["POST"])
def recuperer_cle():
    try:
        import os, requests as req
        data = request.json or {}
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
            # Ne pas révéler si l'email existe ou non (sécurité)
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
        data = request.json or {}
        fiche_id     = (data.get("fiche_id") or "").strip()
        sender_key   = (data.get("sender_key") or "Quelqu'un").strip()
        type_interet = (data.get("type") or "like").strip()  # "like" ou "tres_interesse"

        if not fiche_id:
            return jsonify({"error": "fiche_id requis"}), 400

        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}

        # Récupérer la fiche (nom + email du propriétaire)
        res = req.get(
            f"{supabase_url}/rest/v1/fiches",
            params={"id": f"eq.{fiche_id}", "select": "nom_projet,email_prive,likes,interets"},
            headers=headers,
        )
        rows = res.json() if res.ok else []
        if not rows:
            return jsonify({"error": "Fiche introuvable"}), 404

        fiche = rows[0]

        # Incrémenter le compteur
        field = "interets" if type_interet == "tres_interesse" else "likes"
        new_count = (fiche.get(field) or 0) + 1
        req.patch(
            f"{supabase_url}/rest/v1/fiches",
            params={"id": f"eq.{fiche_id}"},
            headers={**headers, "Content-Type": "application/json"},
            json={field: new_count},
        )

        # Enregistrer dans fiche_interets
        req.post(
            f"{supabase_url}/rest/v1/fiche_interets",
            headers={**headers, "Content-Type": "application/json"},
            json={"fiche_id": fiche_id, "sender_key": sender_key, "type": type_interet},
        )

        # Envoyer le courriel au propriétaire
        if fiche.get("email_prive"):
            send_interet_email(fiche["email_prive"], fiche["nom_projet"], sender_key, type_interet)

        return jsonify({"ok": True, "new_count": new_count})
    except Exception as e:
        print(f"Erreur /1/notifier-interet: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/conversation ────────────────────────────────────────────────────────────
@site2_bp.route("/1/conversation", methods=["POST"])
def site2_conversation():
    # Import ici pour éviter le circular import — on réutilise l'infra Echo en filet de sécurité
    from echo_api import prepare_shared_context, run_paid_cascade, run_free_cascade, is_paid_tier
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="chat")

        # ── Cascade propre à site2 ────────────────────────────────────────────
        # 1. Grok-4.1-fast (non-reasoning) via Requesty — en test
        # 2. Qwen3-235B via Requesty en filet
        # 3. Fallback sur la cascade Echo si Requesty échoue ou n'est pas configuré
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
        steps = [
            ("ds", "deepseek", 8),
            ("z",  "glm",     15),
            ("or", "llama",   12),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /1/conversation: {e}")
        return jsonify(ERR_CRASH), 500

# ── /1/supprimer-fiche — par Key + email, sans session requise ───────────────
@site2_bp.route("/1/supprimer-fiche", methods=["POST"])
def supprimer_fiche():
    try:
        import os, requests as req
        data  = request.json or {}
        key   = (data.get("key") or "").strip()
        email = (data.get("email") or "").strip()

        if not key or not email:
            return jsonify({"error": "Clé et courriel requis"}), 400

        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}

        # Vérifier que la Key ET l'email correspondent à la même fiche
        res = req.get(
            f"{supabase_url}/rest/v1/fiches",
            params={"key": f"eq.{key}", "email_prive": f"eq.{email}", "select": "id"},
            headers=headers,
        )
        rows = res.json() if res.ok else []
        if not rows:
            return jsonify({"error": "Clé ou courriel incorrect."}), 403

        fiche_id = rows[0]["id"]

        del_res = req.delete(
            f"{supabase_url}/rest/v1/fiches",
            params={"id": f"eq.{fiche_id}"},
            headers=headers,
        )
        if not del_res.ok:
            return jsonify({"error": "Échec de la suppression."}), 500

        return jsonify({"deleted": True})
    except Exception as e:
        print(f"Erreur /1/supprimer-fiche: {e}")
        return jsonify(ERR_CRASH), 500

# ── NOTE ── Le checkout Stripe et le webhook de déblocage de fiche vivent
# maintenant dans Next.js (app/api/checkout-fiche/route.ts + le webhook
# Stripe fusionné existant), pas ici. Flask garde seulement la vérification.

# ── VÉRIFIER SI UNE FICHE EST DÉBLOQUÉE POUR UN USER ─────────────────────────
@site2_bp.route("/1/check-unlock", methods=["POST"])
def check_unlock():
    try:
        import requests as req
        data        = request.json or {}
        fiche_id    = (data.get("fiche_id") or "").strip()
        acheteur_id = (data.get("acheteur_id") or "").strip()
        if not fiche_id or not acheteur_id:
            return jsonify({"unlocked": False})

        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}

        res = req.get(
            f"{supabase_url}/rest/v1/tunnels",
            params={"fiche_id": f"eq.{fiche_id}", "acheteur_id": f"eq.{acheteur_id}", "select": "id"},
            headers=headers,
        )
        rows = res.json() if res.ok else []
        return jsonify({"unlocked": len(rows) > 0})
    except Exception as e:
        print(f"Erreur /1/check-unlock: {e}")
        return jsonify({"unlocked": False})