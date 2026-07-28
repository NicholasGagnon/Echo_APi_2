import os
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

client_deepseek = (
    OpenAI(base_url="https://api.deepseek.com", api_key=DEEPSEEK_API_KEY)
    if DEEPSEEK_API_KEY else None
)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Serveur texte.py actif"})

@app.route("/texte/generate", methods=["POST"])
def generate_text():
    if client_deepseek is None:
        return jsonify({"error": "DeepSeek non configuré"}), 500

    # PROMPT SALE : On demande explicitement de COLLER les titres aux paragraphes
    prompt = (
        "Rédige un texte d'environ 500 mots sur un sujet au choix.\n"
        "CONTRAINTE DE FORMAT : Insère un TITRE PRINCIPAL et 4 SOUS-TITRES en MAJUSCULES.\n"
        "IMPORTANT : Colle chaque titre directement au début du paragraphe sans faire aucun saut de ligne après le titre."
    )

    try:
        res = client_deepseek.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Tu génères du texte brut sans sauts de ligne sous les titres."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        raw_text = res.choices[0].message.content or ""
        return jsonify({"text": raw_text})
    except Exception as e:
        print(f"[GENERATION ERROR] {e}")
        return jsonify({"error": "Erreur de génération"}), 500


@app.route("/texte/etape1", methods=["POST"])
def etape1():
    """Étape 1 : Trouve les titres en MAJUSCULES collés au texte, les sépare et met les balises ==="""
    data = request.json or {}
    raw_text = data.get("text", "")

    if not raw_text:
        return jsonify({"text": ""})

    lines = raw_text.splitlines()
    cleaned_blocks = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Regex : Cherche au début de la ligne une suite de mots en MAJUSCULES (le titre)
        # suivie par du texte qui commence par une Majuscule puis minuscule (le paragraphe)
        match = re.match(r'^([A-ZÀ-ÖØ-ß0-9\s\'\-,:!]{4,100}?)(?=\s+[A-ZÀ-ÖØ-ß][a-zà-öø-ÿ]|\n|$)', stripped)

        if match:
            titre = match.group(1).strip()
            reste = stripped[len(match.group(1)):].strip()

            cleaned_blocks.append(f"=== {titre} ===")
            if reste:
                cleaned_blocks.append(reste)
        else:
            cleaned_blocks.append(stripped)

    return jsonify({"text": "\n\n".join(cleaned_blocks).strip()})


@app.route("/texte/etape2", methods=["POST"])
def etape2():
    """Étape 2 : Enlève les balises === et force un double saut de ligne sous le titre"""
    data = request.json or {}
    raw_text = data.get("text", "")

    if not raw_text:
        return jsonify({"text": ""})

    lines = raw_text.splitlines()
    final_blocks = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("===") and stripped.endswith("==="):
            clean_title = stripped.strip("=").strip()
            final_blocks.append(clean_title)
        else:
            final_blocks.append(stripped)

    # Réassemble tout avec un vrai saut de ligne physique (\n\n) entre chaque bloc
    return jsonify({"text": "\n\n".join(final_blocks).strip()})


if __name__ == "__main__":
    print("Démarrage du serveur texte.py sur http://localhost:5001 ...")
    app.run(host="0.0.0.0", port=5001, debug=True)