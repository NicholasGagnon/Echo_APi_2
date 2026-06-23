import os
import io
import re
import json
import base64
import threading
import requests as _requests_lib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from google import genai
from google.genai import types
from openai import OpenAI
from dotenv import load_dotenv

from prompts import generate_system_prompt

load_dotenv()

app = Flask(__name__)
CORS(app)

MODELS = {
    "gemini_free_1":        "gemini-3.1-flash-lite",
    "gemini_free_2":        "gemini-2.5-flash-lite",
    "deepseek":             "deepseek/DeepSeek-V3-0324",
    "kimi":                 "moonshotai/kimi-k2.6",
    "nemotron":             "nvidia/nemotron-3-super-120b-a12b:free",
    "glm":                  "@cf/zai-org/glm-5.2",
    "compound":             "compound-beta",
    "gemini_paid_founder":  "gemini-3.5-flash",
    "gemini_paid_ultra":    "gemini-3.1-flash-lite",
    "gemini_paid_standard": "gemini-2.5-flash-lite",
}

API_KEY_FREE          = os.getenv("API_KEY_FREE", "").strip()
API_KEY_PAID          = os.getenv("API_KEY_PAID", "").strip()
OPENROUTER_API_KEY    = os.getenv("OPENROUTER_API_KEY", "").strip()
GITHUB_API_KEY        = os.getenv("GITHUB_API_KEY", "").strip()
NVIDIA_API_KEY        = os.getenv("NVIDIA_API_KEY", "").strip()
GROQ_API_KEY          = os.getenv("GROQ_API_KEY", "").strip()
CLOUDFLARE_API_TOKEN  = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GITHUB_BASE_URL     = "https://models.github.ai/inference"
NVIDIA_BASE_URL     = "https://integrate.api.nvidia.com/v1"
GROQ_BASE_URL       = "https://api.groq.com/openai/v1"
CLOUDFLARE_BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"

client_gemini_free  = genai.Client(api_key=API_KEY_FREE)  if API_KEY_FREE  else None
client_gemini_paid  = genai.Client(api_key=API_KEY_PAID)  if API_KEY_PAID  else None
client_openrouter   = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
client_github       = OpenAI(base_url=GITHUB_BASE_URL,     api_key=GITHUB_API_KEY)     if GITHUB_API_KEY     else None
client_nvidia       = OpenAI(base_url=NVIDIA_BASE_URL,     api_key=NVIDIA_API_KEY)     if NVIDIA_API_KEY     else None
client_groq         = OpenAI(base_url=GROQ_BASE_URL,       api_key=GROQ_API_KEY)       if GROQ_API_KEY       else None
client_cloudflare   = OpenAI(base_url=CLOUDFLARE_BASE_URL, api_key=CLOUDFLARE_API_TOKEN) if CLOUDFLARE_API_TOKEN else None

_cf_session = _requests_lib.Session()

GLOBAL_FAILOVER_MEMORY_COUNT = 0
MAX_FREE_FAILOVERS = 200

def get_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    return GLOBAL_FAILOVER_MEMORY_COUNT

def increment_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    return GLOBAL_FAILOVER_MEMORY_COUNT

def increment_failover_count():
    global GLOBAL_FAILOVER_MEMORY_COUNT
    GLOBAL_FAILOVER_MEMORY_COUNT += 1
    print(f"[FAILOVER] {GLOBAL_FAILOVER_MEMORY_COUNT} / {MAX_FREE_FAILOVERS}")

MODELS_LOCK_REGISTRY = {}

def is_model_locked(model_key: str) -> bool:
    lock_time = MODELS_LOCK_REGISTRY.get(model_key)
    if lock_time:
        if datetime.now() < lock_time:
            return True
        else:
            del MODELS_LOCK_REGISTRY[model_key]
    return False

def lock_model(model_key: str):
    MODELS_LOCK_REGISTRY[model_key] = datetime.now() + timedelta(seconds=60)
    print(f"[LOCK] {model_key} hors circuit 60s.")

VALID_TIERS = {"connected_free", "basic", "premium", "ultra", "founder"}

def normalize_tier(raw: str) -> str:
    cleaned = (raw or "").lower().strip()
    if cleaned in VALID_TIERS: return cleaned
    if cleaned == "free":      return "connected_free"
    if "founder" in cleaned:   return "founder"
    if "ultra"   in cleaned:   return "ultra"
    if "premium" in cleaned:   return "premium"
    if "basic"   in cleaned:   return "basic"
    return "connected_free"

ERR_QUOTA   = {"action": None, "response": "Le service est temporairement sature. Reessaie dans quelques instants."}
ERR_FINAL   = {"action": None, "response": "Tous les serveurs sont momentanement indisponibles. Reessaie dans 1 minute."}
ERR_CRASH   = {"action": None, "response": "Une erreur inattendue s'est produite. Reessaie dans quelques secondes."}
ERR_HORIZON = {"response": "Le moteur de recherche est temporairement indisponible.", "attributes": [], "matrix": None}

def clean_and_parse_json(raw_text):
    text = raw_text.strip()
    if text.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
http://googleusercontent.com/immersive_entry_chip/2
http://googleusercontent.com/immersive_entry_chip/3
http://googleusercontent.com/immersive_entry_chip/4
http://googleusercontent.com/immersive_entry_chip/5