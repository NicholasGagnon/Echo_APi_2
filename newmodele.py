import os
import sys
from openai import OpenAI

# Récupération de la clé API Requesty
REQUESTY_API_KEY = os.getenv("REQUESTY_API_KEY", "").strip()

if not REQUESTY_API_KEY:
    print("\n[!] ATTENTION : La variable d'environnement REQUESTY_API_KEY n'est pas définie.")
    print("    Tu peux la définir dans ton terminal PowerShell avec :")
    print('    $env:REQUESTY_API_KEY="rqsty-sk-dI+AK/1dSJC7eGhM4ZaggFIKCR1rVc24V99EtFP4KKHToqR3gVbH1RIX4RahhJs/ROXBOy9duwuLoCc9B84RN3UPjov3gvk4Q8c0qILEMAg="')
    # Option de secours : saisie directe si non trouvée
    REQUESTY_API_KEY = input("\nColle ta clé API Requesty ici : ").strip()

client = OpenAI(
    base_url="https://router.requesty.ai/v1",
    api_key=REQUESTY_API_KEY,
)

MODEL_NAME = "gpt-6-astra"

def main():
    print("=" * 60)
    print(f"  Console interactive avec {MODEL_NAME}")
    print("  Tape 'exit', 'quit' ou 'q' pour quitter.")
    print("=" * 60 + "\n")

    history = [
        {"role": "system", "content": "Tu es un assistant IA technique, précis et direct."}
    ]

    while True:
        try:
            user_input = input("\nToi > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print("\nFermeture de la session. À bientôt !")
                break

            history.append({"role": "user", "content": user_input})

            print("\n[Le plus puissant de tous...]")
            res = client.chat.completions.create(
                model=MODEL_NAME,
                messages=history,
                temperature=0.4,
                max_tokens=2500,
                timeout=45.0,
            )

            assistant_reply = res.choices[0].message.content or ""
            print(f"\ngpt-6.1-sol >\n{assistant_reply}\n")

            history.append({"role": "assistant", "content": assistant_reply})

        except KeyboardInterrupt:
            print("\nInterrompu par l'utilisateur. Au revoir !")
            sys.exit(0)
        except Exception as e:
            print(f"\n[Erreur] Impossible de contacter le modèle : {e}")

if __name__ == "__main__":
    main()