import os
import requests
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

ECHO_API_BASE = os.getenv("ECHO_API_URL", "http://127.0.0.1:5000")

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
                label = f"{(limit - usage):.2f}$ restant"
            return {"status": "ok", "label": label, "usage": round(usage, 4), "limit": limit, "ok": True}
        return {"status": "error", "label": f"HTTP {r.status_code}", "ok": False}
    except Exception as e:
        return {"status": "error", "label": f"Erreur: {str(e)[:40]}", "ok": False}


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
        return {"status": "error", "label": f"Erreur: {str(e)[:40]}", "ok": False}


def get_zai_status():
    cle = os.getenv("ZAI_API_KEY")
    if not cle:
        return {"status": "error", "label": "Clé absente", "ok": False}
    try:
        r = requests.post(
            "https://api.z.ai/api/paas/v4/chat/completions",
            headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
            json={"model": "glm-4-32b-0414-128k", "messages": [{"role": "user", "content": "1"}], "max_tokens": 1},
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
        return {"status": "error", "label": f"Erreur: {str(e)[:40]}", "ok": False}


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
            count = len(r.json().get("models", []))
            return {"status": "ok", "label": f"Plan Paid OK — {count} modèles", "ok": True}
        return {"status": "error", "label": f"Erreur {r.status_code}", "ok": False}
    except Exception:
        return {"status": "error", "label": "Inaccessible", "ok": False}


# ── ENDPOINTS CHECK ───────────────────────────────────────────────────────────

def check_endpoint(path, method="GET", payload=None, timeout=6):
    import time
    try:
        url = f"{ECHO_API_BASE}{path}"
        t0  = time.time()
        if method == "POST":
            r = requests.post(url, json=payload or {}, timeout=timeout)
        else:
            r = requests.get(url, timeout=timeout)
        ms = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            return {"status": "ok", "label": "200 OK", "ok": True, "ms": ms}
        return {"status": "warn", "label": f"HTTP {r.status_code}", "ok": False, "ms": ms}
    except requests.exceptions.Timeout:
        return {"status": "warn", "label": "Timeout", "ok": False, "ms": None}
    except Exception as e:
        return {"status": "error", "label": f"Down", "ok": False, "ms": None}


def get_echo_stats():
    try:
        r = requests.get(f"{ECHO_API_BASE}/stats", timeout=5)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


# ── ROUTE PRINCIPALE ──────────────────────────────────────────────────────────

@app.route("/api/monitoring")
def get_monitoring_data():

    # Balances
    openrouter = get_openrouter_balance()
    deepseek   = get_deepseek_balance()
    zai        = get_zai_status()
    gemini     = get_gemini_status()

    # Endpoints
    ping           = check_endpoint("/ping",           "GET")
    ep_horizon     = check_endpoint("/horizon",        "POST", {"query": "test ping", "userTier": "connected_free"}, timeout=35)
    ep_horizon_pre = check_endpoint("/horizon-pre",    "POST", {"query": "test"})
    ep_warmup      = check_endpoint("/horizon-warmup", "POST", {"partial": "test"})
    ep_chat        = check_endpoint("/chat",           "POST", {"message": "ping", "userTier": "connected_free", "history": []})
    ep_vitality    = check_endpoint("/vitality",       "POST", {"message": "ping", "userTier": "connected_free", "history": []})
    ep_history     = check_endpoint("/history",        "POST", {"message": "ping", "userTier": "connected_free", "history": []})
    ep_books       = check_endpoint("/books",          "POST", {"message": "ping", "userTier": "connected_free", "history": [], "bookTitle": "test"})

    # Stats internes echo_api
    echo_stats = get_echo_stats()

    # Score global
    providers_ok  = sum([openrouter["ok"], deepseek["ok"], zai["ok"], gemini["ok"]])
    endpoints_ok  = sum([ping["ok"], ep_chat["ok"], ep_vitality["ok"]])
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
            "history":        ep_history,
            "books":          ep_books,
        },
        "echo_stats": echo_stats,
        "models_active": [
            "gemini-2.5-flash-lite (grounding)",
            "gemini-3.1-flash-lite (grounding)",
            "mistral-small-24b",
            "ling-2.6-flash (warmup)",
            "deepseek-chat",
            "glm-4-32b (Z.AI)",
            "llama-3.3-70b",
            "owl-alpha (history)",
        ],
    })


@app.route("/api/monitoring/ping")
def monitoring_ping():
    return jsonify({"status": "monitoring alive"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)