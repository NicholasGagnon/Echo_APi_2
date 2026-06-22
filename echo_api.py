# Ajoutez cette fonction d'extraction juste avant vos routes

def extract_attributes_and_matrix(query, ctx, attempt=1, max_attempts=3):
    """
    Boucle agentique d'HorizonWeb. 
    Applique les filtres en tâche de fond via le prompt système dédié,
    détecte les attributs décisionnels et valide la structure des 8 piliers (Règle 10).
    """
    if attempt > max_attempts:
        return {
            "matrix": {
                "c_est_quoi": "Erreur d'extraction structurelle.",
                "est_ce_bon": "Le signal web est trop fragmenté pour être validé.",
                "combien_ca_coute": "Non disponible.",
                "est_ce_disponible": "Non disponible.",
                "qu_en_pensent_les_gens": "Données incohérentes.",
                "quelles_sont_les_alternatives": "Non disponible.",
                "quels_sont_les_risques": "Instabilité du flux détectée.",
                "quelle_option_est_recommandee": "Echo a interrompu la boucle pour cause d'incohérence persistante."
            },
            "attributes": ["erreur_coherence"]
        }

    # Injection des directives spécifiques d'HorizonWeb pour forcer le formatage strict
    horizon_directive = (
        "\n\n[HORIZONWEB PROTOCOL]\n"
        "Tu es en mode exploration extérieure. Tu dois obligatoirement renvoyer un objet JSON valide "
        "contenant deux clés principales :\n"
        "1) 'attributes': une liste de 3 à 5 mots-clés (en minuscules) représentant les critères décisionnels spécifiques détectés pour ce sujet précis.\n"
        "2) 'matrix': un objet contenant exactement ces 8 clés :\n"
        "   - 'c_est_quoi'\n"
        "   - 'est_ce_bon'\n"
        "   - 'combien_ca_coute'\n"
        "   - 'est_ce_disponible'\n"
        "   - 'qu_en_pensent_les_gens'\n"
        "   - 'quelles_sont_les_alternatives'\n"
        "   - 'quels_sont_les_risques'\n"
        "   - 'quelle_option_est_recommandee'\n"
        "Applique rigoureusement les 10 filtres universels (Source Primaire, Réalité Terrain, Coût Réel, etc.) pour épurer ton signal avant de remplir la matrice."
    )
    
    ctx["system_prompt"] += horizon_directive
    
    try:
        # Sélection du modèle selon la structure de coûts de ton app
        if ctx["user_tier"] == "connected_free":
            model = "gemini-3.1-flash-lite"
            client = client_gemini_free if client_gemini_free else client_gemini_paid
        else:
            model = "gemini-3.5-flash" if ctx["user_tier"] == "founder" else "gemini-3.1-flash-lite"
            client = client_gemini_paid

        # Appel à l'infrastructure Gemini
        r = execute_gemini_call(client, model, ctx)
        raw_text = r.text
        
        # Nettoyage et parsing standard de ton app
        parsed_json = clean_and_parse_json(raw_text)
        
        # Validation de la structure (Règle 10 : Cohérence & Structure)
        # Si la réponse est un texte brut enveloppé ou s'il manque la matrice, on considère que c'est un bug
        if not isinstance(parsed_json, dict) or "matrix" not in parsed_json or "attributes" not in parsed_json:
            print(print(f"[HORIZON AGENT] Tentative {attempt} échouée (Structure invalide). Relancement..."))
            return extract_attributes_and_matrix(query, ctx, attempt + 1, max_attempts)
            
        # Validation des 8 clés intérieures
        required_keys = [
            "c_est_quoi", "est_ce_bon", "combien_ca_coute", "est_ce_disponible", 
            "qu_en_pensent_les_gens", "quelles_sont_les_alternatives", 
            "quels_sont_les_risques", "quelle_option_est_recommandee"
        ]
        if not all(k in parsed_json["matrix"] for k in required_keys):
            print(f"[HORIZON AGENT] Tentative {attempt} échouée (Clés manquantes dans la matrice). Relancement..."))
            return extract_attributes_and_matrix(query, ctx, attempt + 1, max_attempts)

        return parsed_json

    except Exception as e:
        print(f"[HORIZON AGENT] Erreur crash à la tentative {attempt}: {e}")
        return extract_attributes_and_matrix(query, ctx, attempt + 1, max_attempts)


# ── NOUVELLE ROUTE /horizon ───────────────────────────────────────────────────
@app.route("/horizon", methods=["POST"])
def horizon():
    try:
        data = request.json or {}
        query = data.get("query", "").strip()
        
        if not query:
            return jsonify({"error": "L'intention d'exploration est vide."}), 400

        # On adapte le payload pour simuler un message utilisateur classique pour ton prepare_shared_context
        data["message"] = f"Fais une recherche web complète et extrait tout sur : {query}"
        
        # Préparation du contexte unifié avec le tag de source 'horizonweb'
        ctx = prepare_shared_context(data, source_override="horizonweb")
        
        # Sécurité Connected Free existante dans ton code
        if ctx["user_tier"] == "connected_free":
            if get_failover_count() >= MAX_FREE_FAILOVERS:
                return jsonify({
                    "matrix": {"quelle_option_est_recommandee": "Ouf, mon sillage Horizon sature ! 😎"},
                    "attributes": ["quota_atteint"]
                })

        # Lancement de la boucle d'extraction agentique
        result = extract_attributes_and_matrix(query, ctx)
        
        return jsonify(result)

    except Exception as e:
        print(f"Erreur critique sur la route /horizon: {e}")
        return jsonify({
            "matrix": {"quelle_option_est_recommandee": "Système Horizon instable, l'axe n'a pas pu se stabiliser."},
            "attributes": ["erreur_critique"]
        }), 500