import time
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from zhipuai import ZhipuAI
from video_pipeline import assembler_video_finale, OUTPUT_DIR

app = Flask(__name__)
CORS(app)

client = ZhipuAI(api_key="e8560ff5028048b8ac0a24c74f44ab94.lhMCIoOL1cyPKYVy")


def analyser_image(image_base64: str, mimetype: str) -> str:
    """Envoie l'image à GLM-4.6V-Flash pour obtenir une description détaillée."""
    print("🔍 Analyse de l'image en cours...")

    response = client.chat.completions.create(
        model="glm-4.6v-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mimetype};base64,{image_base64}"},
                    },
                    {
                        "type": "text",
                        "text": "Décris cette image en détail : le sujet, le style visuel, les couleurs, l'ambiance, la composition. Réponds en français, de façon concise.",
                    },
                ],
            }
        ],
    )

    description = response.choices[0].message.content
    print(f"✅ Description obtenue : {description}")
    return description


@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_message = request.form.get("message", "")
        image_base64 = request.form.get("image_base64")
        image_mimetype = request.form.get("image_mimetype", "image/jpeg")
        texte_narration = request.form.get("narration", "")

        if not user_message and not image_base64:
            return jsonify({"response": "Un prompt texte ou une image est requis."}), 400

        print(f"\n🚀 Prompt reçu : {user_message or '(aucun texte, image seule)'}")

        final_prompt = user_message

        if image_base64:
            try:
                description_image = analyser_image(image_base64, image_mimetype)
                if user_message:
                    final_prompt = f"{user_message}\n\nAmbiance visuelle inspirée de : {description_image}\n\nIMPORTANT : ne pas afficher de texte, d'interface, de boutons ou d'écran d'ordinateur visibles. Montrer uniquement une personne qui parle avec confiance dans un environnement professionnel avec un humain."
                else:
                    final_prompt = f"Crée une vidéo basée sur cette scène : {description_image}"
            except Exception as e:
                print(f"⚠️ Erreur lors de l'analyse de l'image : {str(e)}")
                if not user_message:
                    return jsonify({"response": f"Impossible d'analyser l'image : {str(e)}"}), 500

        print(f"📝 Prompt final envoyé au modèle vidéo : {final_prompt}")
        print("📡 Envoi de la tâche via le SDK officiel ZhipuAI...")

        response = client.videos.generations(
    model="viduq1-text",
    prompt=final_prompt,
    with_audio=False,
)

        task_id = response.id
        print(f" Task créée ! ID : {task_id}. Début du polling...")

        status = "PROCESSING"
        video_url = ""
        attempts = 0

        while status in ["PROCESSING", "QUEUEING"] and attempts < 90:
            time.sleep(5)
            attempts += 1
            print(f" ⏳ Vérification du statut... ({attempts}/90)")

            task_check = client.videos.retrieve_videos_result(id=task_id)
            status = task_check.task_status
            print(f"    Statut actuel : {status}")

            if status == "SUCCESS":
                video_url = task_check.video_result[0].url
                break
            elif status == "FAIL":
                return jsonify({"response": "La génération de la vidéo a échoué sur les serveurs de l'IA."}), 500

        if not video_url:
            return jsonify({"response": "Délai d'attente dépassé (Timeout)."}), 504

        print(f" 🎉 Vidéo brute générée ! URL : {video_url}")

        texte_a_lire = texte_narration or user_message

        segments_texte = [
    {"texte": texte_a_lire[:60], "debut": 0, "fin": 5}
]

        chemin_final = assembler_video_finale(
            video_url=video_url,
            texte_narration=texte_a_lire,
            segments_texte=segments_texte,
        )

        nom_fichier_final = os.path.basename(chemin_final)

        return jsonify({
            "response": "Voici votre vidéo générée avec voix et texte synchronisés :",
            "video_url": f"http://127.0.0.1:5000/outputs/{nom_fichier_final}",
        }), 200

    except Exception as e:
        print(f"❌ Erreur critique Flask : {str(e)}")
        return jsonify({"response": f"Erreur interne du serveur local : {str(e)}"}), 500


@app.route("/outputs/<path:filename>")
def servir_video(filename):
    """Permet au frontend d'accéder aux vidéos finales générées."""
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    app.run(port=5000, debug=True)