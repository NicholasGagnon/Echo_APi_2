import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Récupération de la clé Free uniquement
API_KEY_FREE = os.getenv("API_KEY_FREE", "").strip()
print(f"📡 [INIT] Clé API Free : {API_KEY_FREE[:6]}...{API_KEY_FREE[-4:] if len(API_KEY_FREE) > 4 else ''}")

# Initialisation du client unique
client_gemini_free = genai.Client(api_key=API_KEY_FREE) if API_KEY_FREE else None

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "raw_free_mode", "engine": "gemini-free-only"}), 200

@app.route("/chat", methods=["POST"])
def chat():
    if not client_gemini_free:
        print("❌ [ERREUR] Client API Free non initialisé.")
        return jsonify({"action": None, "response": "Erreur backend : Clé manquante."}), 500

    try:
        data = request.json or {}
        user_message = data.get("message", "")
        
        print(f"📥 [REQUÊTE] Message : '{user_message}'")

        # Appel brut sans aucune contrainte JSON ou Search
        response = client_gemini_free.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=user_message,
            config=types.GenerateContentConfig(
                max_output_tokens=1024
            )
        )

        print(f"📦 [REPONSE BRUTE] : {response}")

        if response and hasattr(response, 'text') and response.text:
            print(f"✅ [SUCCÈS] : {response.text}")
            return jsonify({"action": None, "response": response.text})
        else:
            print("⚠️ [ATTENTION] Le champ .text est absent ou vide.")
            return jsonify({"action": None, "response": "Sillage vide. Réessaie."})

    except Exception as e:
        print(f"💥 [CRASH] Erreur brute de l'appel Google : {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "action": None, 
            "response": f"Détection du blocage Free brute : {str(e)}"
        }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)