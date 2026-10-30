import os
import sys
from openai import OpenAI

# Récupération de la clé API Requesty
REQUESTY_API_KEY = os.getenv("REQUESTY_API_KEY", "").strip()

if not REQUESTY_API_KEY:
    REQUESTY_API_KEY = "rqsty-sk-dI+AK/1dSJC7eGhM4ZaggFIKCR1rVc24V99EtFP4KKHToqR3gVbH1RIX4RahhJs/ROXBOy9duwuLoCc9B84RN3UPjov3gvk4Q8c0qILEMAg="

client = OpenAI(
    base_url="https://router.requesty.ai/v1",
    api_key=REQUESTY_API_KEY,
)

MODEL_NAME = "openai/gpt-5.6-sol:flex"
BOT_NAME = "Ankahr"

def main():
    print("=" * 60)
    print(f"  Console interactive avec {BOT_NAME} ({MODEL_NAME})")
    print("  Tape 'exit', 'quit' ou 'q' pour quitter.")
    print("=" * 60 + "\n")

    history = [
        {
            "role": "system",
            "content": f"Tu es {BOT_NAME}, un assistant sans filtre inutile, direct, joueur et précis.",
        }
    ]

    while True:
        try:
            user_input = input("\nToi > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print(f"\nFermeture de la session avec {BOT_NAME}. À plus !")
                break

            history.append({"role": "user", "content": user_input})

            print(f"\n[{BOT_NAME} réfléchit...]")
            res = client.chat.completions.create(
                model=MODEL_NAME,
                messages=history,
                temperature=0.7,
                max_tokens=2500,
                timeout=45.0,
            )

            assistant_reply = res.choices[0].message.content or ""
            print(f"\n{BOT_NAME} >\n{assistant_reply}\n")

            history.append({"role": "assistant", "content": assistant_reply})

        except KeyboardInterrupt:
            print("\nInterrompu. Fermeture !")
            sys.exit(0)
        except Exception as e:
            print(f"\n[Erreur] Impossible de contacter le modèle : {e}")

if __name__ == "__main__":
    main()