from openai import OpenAI

# 1. Initialisation avec la vraie URL globale de Vercel pour l'API OpenAI
client = OpenAI(
    base_url="https://ai-gateway.vercel.sh/v1",
    api_key="vck_1v9SOTloxe7HChzSRngxBsyBvHoM50zMhN8kOqPvoKMRPb93sv39dr2z"
)

try:
    print("🚀 Envoi de la requête de test à DeepSeek via Vercel...")
    
    # On spécifie le provider directement dans le nom du modèle (deepseek/...)
    response = client.chat.completions.create(
        model="deepseek/deepseek-chat",
        messages=[{"role": "user", "content": "Dit simplement 'Connexion réussie'"}]
    )
    
    print("\n🟢 RÉPONSE REÇUE :")
    print(response.choices[0].message.content)
    print("\n⚡ C'est fait ! Regarde ton dashboard Vercel pour voir si la ligne s'affiche.")

except Exception as e:
    print("\n❌ ERREUR LORS DU TEST :")
    print(e)