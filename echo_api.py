# ════════════════════════════════════════════════════════════════════════════
# PATCH app.py — Ajouter ces 2 sections
# ════════════════════════════════════════════════════════════════════════════

# ── 1. IMPORT en haut de app.py (après les autres imports) ──────────────────
from export_handler import handle_export


# ── 2. ROUTE /export (ajouter n'importe où après les autres routes) ─────────
@app.route("/export", methods=["POST"])
def export_route():
    """
    Reçoit : { format: "pdf"|"docx"|"epub"|"txt", title: str, html: str }
    Retourne : fichier binaire téléchargeable
    """
    return handle_export()


# ── 3. ROUTE /books — REMPLACER ou AJOUTER si elle n'existe pas ─────────────
#
# Logique d'injection : si le message contient "inject" ou "injecte",
# Flask retourne { inject: true, inject_text: "...", response: "..." }
# Le frontend TipTap détecte ça et insère inject_text à la fin du chapitre.
#
@app.route("/books", methods=["POST"])
def books_route():
    data    = request.json or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])
    tier    = normalize_tier(data.get("userTier", "connected_free"))
    buttons = data.get("selectedButtons", [])  # ["creative"] | ["ideas"] | ["critical"] | []
    book_title  = data.get("bookTitle", "")
    user_id     = data.get("userId", None)

    # Détection injection
    INJECT_KEYWORDS = ["inject", "injecte", "ajoute", "insère", "écris ici", "write here", "add this"]
    wants_inject = any(kw in message.lower() for kw in INJECT_KEYWORDS)

    # Système prompt selon mode
    mode_prompts = {
        "creative": "Tu es en mode Créatif. Génère du contenu littéraire original, avec des métaphores et un style soigné.",
        "ideas":    "Tu es en mode Idées. Propose des pistes narratives, rebondissements et développements possibles.",
        "critical": "Tu es en mode Critique. Analyse le texte avec rigueur : rythme, cohérence, clarté, redondances.",
    }
    active_mode = buttons[0] if buttons else None
    mode_instruction = mode_prompts.get(active_mode, "Tu es un assistant d'écriture créatif et polyvalent.")

    inject_instruction = ""
    if wants_inject:
        inject_instruction = (
            "\n\nL'utilisateur veut que tu INJECTES du texte directement dans son livre. "
            "Génère le passage demandé et termine ta réponse avec exactement ce marqueur sur une nouvelle ligne :\n"
            "<<<INJECT_TEXT>>>\n"
            "[ici le texte à injecter, sans balises HTML, juste du texte propre]\n"
            "<<<END_INJECT>>>"
        )

    system_prompt = (
        f"{mode_instruction}{inject_instruction}\n\n"
        f"Tu travailles sur le livre intitulé : \"{book_title}\".\n"
        "Réponds en moins de 400 mots sauf si l'utilisateur demande un long passage. "
        "Sois direct, utile et élégant."
    )

    # Construction de l'historique
    gemini_history = []
    for msg in history[-10:]:  # Garder les 10 derniers messages
        if msg.startswith("You: "):
            gemini_history.append(types.Content(role="user", parts=[types.Part(text=msg[5:])]))
        elif msg.startswith("Echo: "):
            gemini_history.append(types.Content(role="model", parts=[types.Part(text=msg[6:])]))

    # Choisir le client Gemini selon le tier
    client = client_gemini_paid if tier in ("premium", "ultra", "founder") else client_gemini_free
    model  = "gemini-2.0-flash" if tier in ("premium", "ultra", "founder") else "gemini-2.0-flash-lite"

    try:
        gemini_history.append(types.Content(role="user", parts=[types.Part(text=message)]))

        resp = client.models.generate_content(
            model=model,
            contents=gemini_history,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1200,
                temperature=0.85,
            )
        )
        full_text = resp.text or ""

        # Parser l'injection si présente
        if wants_inject and "<<<INJECT_TEXT>>>" in full_text:
            parts     = full_text.split("<<<INJECT_TEXT>>>")
            response  = parts[0].strip()
            inject_raw = parts[1].split("<<<END_INJECT>>>")[0].strip() if len(parts) > 1 else ""
            return jsonify({
                "response":    response or "Voici le passage — je l'injecte dans ton chapitre.",
                "inject":      True,
                "inject_text": inject_raw,
                "action":      None,
            })

        return jsonify({"response": full_text, "inject": False, "action": None})

    except Exception as e:
        print(f"❌ [/books ERROR] {e}")
        return jsonify({"response": "Impossible de joindre le modèle.", "inject": False, "action": None}), 500