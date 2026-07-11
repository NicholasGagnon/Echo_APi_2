"""
Test de disponibilité de tous les modèles utilisés dans site2.py + echo_api.py,
SAUF les modèles Gemini et DeepSeek (exclus volontairement).

Couvre :
- Requesty  (router.requesty.ai)
- OpenRouter
- Z.AI (GLM)

Usage :
    python test_models.py
    python test_models.py --timeout 15
    python test_models.py --only requesty
"""

import os
import sys
import time
import argparse
from dataclasses import dataclass
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

PING_MESSAGES = [
    {"role": "system", "content": "You are a health check ping. Reply with exactly one word."},
    {"role": "user", "content": "ping"},
]


@dataclass
class ModelTarget:
    provider: str      # "requesty" | "openrouter" | "zai"
    model_id: str       # nom du modèle tel qu'utilisé dans l'appel API
    label: str           # d'où il vient dans le code, pour le rapport


# ── Liste des modèles à tester (extraits de site2.py et echo_api.py) ─────────
# Exclus : tout ce qui est gemini-*, deepseek-* / deepseek-v4-flash
TARGETS = [
    # -- site2.py : SITE2_MODELS --
    ModelTarget("requesty", "xai/grok-4-1-fast-non-reasoning", "SITE2_MODELS['grok']"),
    ModelTarget("requesty", "deepinfra/Qwen/Qwen3-235B-A22B-Instruct-2507", "SITE2_MODELS['qwen3']"),

    # -- site2.py : /2/analyse-idee --
    ModelTarget("requesty", "xai/grok-4-fast-non-reasoning", "analyse_idee (1er essai)"),
    ModelTarget("requesty", "xai/grok-4-fast", "analyse_idee (essai final)"),

    # -- site2.py : WORLD_MODELS --
    ModelTarget("requesty", "xai/grok-4-fast-non-reasoning", "WORLD_MODELS['na_1']"),
    ModelTarget("openrouter", "openai/gpt-4o-mini-search-preview", "WORLD_MODELS['na_3']"),
    ModelTarget("requesty", "deepinfra/Qwen/Qwen3-235B-A22B-Instruct-2507", "WORLD_MODELS['cn_2']"),
    ModelTarget("requesty", "deepinfra/Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo", "WORLD_MODELS['cn_3']"),
    ModelTarget("requesty", "mistral/mistral-small-latest", "WORLD_MODELS['eu_1']"),
    ModelTarget("openrouter", "mistralai/mistral-small-2603", "WORLD_MODELS['eu_2']"),
    ModelTarget("requesty", "mistral/mistral-small-2603", "WORLD_MODELS['eu_3']"),

    # -- site2.py : /world/warmup --
    ModelTarget("openrouter", "inclusionai/ling-2.6-flash", "world_warmup"),
    ModelTarget("openrouter", "amazon/nova-lite-v1", "world_warmup"),
    ModelTarget("openrouter", "mistralai/ministral-3b-2512", "world_warmup"),

    # -- echo_api.py : MODELS --
    ModelTarget("openrouter", "amazon/nova-lite-v1", "MODELS['mistral']"),
    ModelTarget("openrouter", "tencent/hy3-preview", "MODELS['hy3']"),
    ModelTarget("openrouter", "openrouter/owl-alpha", "MODELS['owl']"),
    ModelTarget("openrouter", "meta-llama/llama-3.3-70b-instruct", "MODELS['llama']"),
    ModelTarget("openrouter", "inclusionai/ling-2.6-flash", "MODELS['ling']"),
    ModelTarget("zai", "GLM-4.5-Air", "MODELS['glm']"),
]


def dedupe(targets):
    """Retire les doublons (même provider + même model_id), garde la 1re occurrence."""
    seen = set()
    unique = []
    for t in targets:
        key = (t.provider, t.model_id)
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def build_clients():
    requesty_key   = os.getenv("REQUESTY_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    zai_key        = os.getenv("ZAI_API_KEY", "").strip()

    clients = {}
    if requesty_key:
        clients["requesty"] = OpenAI(base_url="https://router.requesty.ai/v1", api_key=requesty_key)
    if openrouter_key:
        clients["openrouter"] = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    if zai_key:
        clients["zai"] = OpenAI(base_url="https://api.z.ai/api/paas/v4", api_key=zai_key)

    missing = [name for name, key in [("REQUESTY_API_KEY", requesty_key),
                                       ("OPENROUTER_API_KEY", openrouter_key),
                                       ("ZAI_API_KEY", zai_key)] if not key]
    if missing:
        print(f"[WARN] Clés manquantes dans l'env : {', '.join(missing)} — tests correspondants sautés.\n")

    return clients


def test_model(client, target: ModelTarget, timeout: float):
    start = time.time()
    try:
        res = client.chat.completions.create(
            model=target.model_id,
            messages=PING_MESSAGES,
            temperature=0.1,
            max_tokens=10,
            timeout=timeout,
        )
        elapsed = time.time() - start
        content = res.choices[0].message.content
        if content and content.strip():
            return True, elapsed, content.strip().replace("\n", " ")[:40]
        return False, elapsed, "réponse vide"
    except Exception as e:
        elapsed = time.time() - start
        return False, elapsed, str(e)[:150]


def main():
    parser = argparse.ArgumentParser(description="Test des modèles (hors Gemini/DeepSeek)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout par appel (secondes)")
    parser.add_argument("--only", choices=["requesty", "openrouter", "zai"], default=None,
                         help="Ne tester qu'un seul provider")
    args = parser.parse_args()

    clients = build_clients()
    targets = dedupe(TARGETS)
    if args.only:
        targets = [t for t in targets if t.provider == args.only]

    print(f"Test de {len(targets)} modèle(s) uniques (timeout={args.timeout}s)\n")
    print(f"{'PROVIDER':<11} {'MODÈLE':<55} {'STATUT':<8} {'TEMPS':<8} DÉTAIL")
    print("-" * 120)

    results = []
    for t in targets:
        client = clients.get(t.provider)
        if client is None:
            print(f"{t.provider:<11} {t.model_id:<55} {'SKIP':<8} {'-':<8} clé API absente")
            results.append((t, None, None, "clé absente"))
            continue

        ok, elapsed, detail = test_model(client, t, args.timeout)
        status = "OK" if ok else "ÉCHEC"
        print(f"{t.provider:<11} {t.model_id:<55} {status:<8} {elapsed:>5.1f}s   {detail}")
        results.append((t, ok, elapsed, detail))

    print("\n" + "=" * 120)
    ok_count   = sum(1 for _, ok, _, _ in results if ok is True)
    fail_count = sum(1 for _, ok, _, _ in results if ok is False)
    skip_count = sum(1 for _, ok, _, _ in results if ok is None)
    print(f"Résumé : {ok_count} OK / {fail_count} échec(s) / {skip_count} sauté(s) sur {len(results)} modèles testés")

    if fail_count:
        print("\nModèles en échec :")
        for t, ok, elapsed, detail in results:
            if ok is False:
                print(f"  - [{t.provider}] {t.model_id}  (utilisé dans: {t.label})  →  {detail}")

    sys.exit(1 if fail_count else 0)


if __name__ == "__main__":
    main()