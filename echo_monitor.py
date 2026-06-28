import os
import requests
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── BALANCES ──────────────────────────────────────────────────────────────────

def get_openrouter_balance():
    cle = os.getenv("OPENROUTER_API_KEY")
    if not cle:
        return {"status": "error", "label": "Clé absente", "ok": False}
    try:
        r = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {cle}"},
            timeout=5,
        )
        if r.status_code == 200:
            data  = r.json().get("data", {})
            limit = data.get("limit")
            usage = data.get("usage", 0)
            if limit is None or limit == 0:
                label = f"Usage: {usage:.2f}$"
            else:
                restant = limit - usage
                label   = f"{restant:.2f}$ restant"
            return {"status": "ok", "label": label, "usage": round(usage, 4), "limit": limit, "ok": True}
        return {"status": "error", "label": f"HTTP {r.status_code}", "ok": False}
    except Exception as e:
        return {"status": "error", "label": f"Erreur: {str(e)}", "ok": False}


def get_deepseek_balance():
    cle = os.getenv("DEEPSEEK_API_KEY")
    if not cle:
        return {"status": "error", "label": "Clé absente", "ok": False}
    try:
        r = requests.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {cle}"},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("is_available"):
                infos = data.get("balance_infos", [{}])[0]
                solde = infos.get("total_balance", "0")
                return {"status": "ok", "label": f"{solde}$", "balance": solde, "ok": True}
            return {"status": "warn", "label": "Compte inactif", "ok": False}
        return {"status": "error", "label": f"HTTP {r.status_code}", "ok": False}
    except Exception as e:
        return {"status": "error", "label": f"Erreur: {str(e)}", "ok": False}


def get_zai_balance():
    cle = os.getenv("ZAI_API_KEY")
    if not cle:
        return {"status": "error", "label": "Clé absente", "ok": False}
    # Z.AI n'expose pas d'endpoint balance public documenté
    # On valide juste que la clé est présente et le modèle accessible
    try:
        r = requests.post(
            "https://api.z.ai/api/paas/v4/chat/completions",
            headers={
                "Authorization": f"Bearer {cle}",
                "Content-Type": "application/json",
            },
            json={
                "model": "glm-4-32b-0414-128k",
                "messages": [{"role": "user", "content": "1"}],
                "max_tokens": 1,
            },
            timeout=8,
        )
        if r.status_code == 200:
            return {"status": "ok", "label": "GLM actif ✓", "ok": True}
        elif r.status_code == 401:
            return {"status": "error", "label": "Clé invalide", "ok": False}
        elif r.status_code == 429:
            return {"status": "warn", "label": "Rate limit", "ok": True}
        return {"status": "warn", "label": f"HTTP {r.status_code}", "ok": False}
    except Exception as e:
        return {"status": "error", "label": f"Erreur: {str(e)}", "ok": False}


def get_gemini_status():
    cle = os.getenv("API_KEY_PAID")
    if not cle:
        return {"status": "error", "label": "Clé absente", "ok": False}
    try:
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={cle}",
            timeout=5,
        )
        if r.status_code == 200:
            models = r.json().get("models", [])
            count  = len(models)
            return {"status": "ok", "label": f"Plan Paid OK — {count} modèles", "ok": True}
        return {"status": "error", "label": f"Erreur {r.status_code}", "ok": False}
    except Exception:
        return {"status": "error", "label": "Inaccessible", "ok": False}


# ── ENDPOINTS STATUS ──────────────────────────────────────────────────────────

ECHO_API_BASE = os.getenv("ECHO_API_URL", "http://127.0.0.1:5000")

def check_endpoint(path: str, method: str = "GET", payload: dict = None, timeout: int = 6):
    try:
        url = f"{ECHO_API_BASE}{path}"
        if method == "POST":
            r = requests.post(url, json=payload or {}, timeout=timeout)
        else:
            r = requests.get(url, timeout=timeout)

        if r.status_code == 200:
            return {"status": "ok", "label": "200 OK", "ok": True, "ms": None}
        return {"status": "warn", "label": f"HTTP {r.status_code}", "ok": False}
    except requests.exceptions.Timeout:
        return {"status": "warn", "label": "Timeout", "ok": False}
    except Exception as e:
        return {"status": "error", "label": f"Down: {str(e)[:40]}", "ok": False}


# ── ROUTE PRINCIPALE ──────────────────────────────────────────────────────────

@app.route("/api/monitoring")
def get_monitoring_data():

    # Balances API
    openrouter = get_openrouter_balance()
    deepseek   = get_deepseek_balance()
    zai        = get_zai_balance()
    gemini     = get_gemini_status()

    # Endpoints Echo
    ping          = check_endpoint("/ping",           "GET")
    ep_horizon    = check_endpoint("/horizon",        "POST", {"query": "test", "userTier": "connected_free"})
    ep_chat       = check_endpoint("/chat",           "POST", {"message": "ping", "userTier": "connected_free", "history": []})
    ep_vitality   = check_endpoint("/vitality",       "POST", {"message": "ping", "userTier": "connected_free", "history": []})
    ep_horizon_pre= check_endpoint("/horizon-pre",    "POST", {"query": "test"})
    ep_warmup     = check_endpoint("/horizon-warmup", "POST", {"partial": "test"})

    # Score global
    providers_ok  = sum([openrouter["ok"], deepseek["ok"], zai["ok"], gemini["ok"]])
    endpoints_ok  = sum([ping["ok"], ep_horizon["ok"], ep_chat["ok"]])
    global_status = "ok" if providers_ok >= 3 and endpoints_ok >= 2 else ("warn" if providers_ok >= 2 else "error")

    return jsonify({
        "global": global_status,
        "providers": {
            "openrouter": openrouter,
            "deepseek":   deepseek,
            "zai":        zai,
            "gemini":     gemini,
        },
        "endpoints": {
            "ping":           ping,
            "horizon":        ep_horizon,
            "horizon_pre":    ep_horizon_pre,
            "horizon_warmup": ep_warmup,
            "chat":           ep_chat,
            "vitality":       ep_vitality,
        },
        "models_active": [
            "gemini-2.5-flash-lite (grounding)",
            "gemini-3.1-flash-lite (grounding)",
            "mistral-small-24b",
            "ling-2.6-flash (warmup)",
            "deepseek-chat",
            "glm-4-32b (Z.AI)",
        ],
    })


@app.route("/api/monitoring/ping")
def monitoring_ping():
    return jsonify({"status": "monitoring alive"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)