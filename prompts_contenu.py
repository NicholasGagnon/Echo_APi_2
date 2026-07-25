# prompts_contenu.py

FORMAT_INSTRUCTION = """
RÈGLES STRICTES DE STRUCTURE VISUELLE ET FORMATAGE (LIVRE & IMPRESSION) :

1. SAUTS DE LIGNE OBLIGATOIRES :
   - Tu DOIS sauter DEUX LIGNES (appuie deux fois sur Entrée) entre chaque paragraphe, sous-titre et point d'ancrage.
   - Ne colle JAMAIS un sous-titre ou un titre de chapitre à la fin d'un paragraphe.

2. TITRES ET SOUS-TITRES :
   - TITRES PRINCIPAUX (CHAPITRES) : Écris '# CHAPITRE X : TITRE' sur sa propre ligne avec deux sauts de ligne avant et après.
   - SOUS-TITRES (SECTIONS) : Écris '## Titre de Section' sur sa propre ligne avec deux sauts de ligne avant et après.

3. STRUCTURE DES PARAGRAPHES ET ANCRAGES :
   - Limite chaque paragraphe à 3 ou 4 lignes MAXIMUM.
   - Démarre régulièrement les paragraphes clés avec une formule forte en MAJUSCULES (ex: LE CONSTAT :, L'ACTION CONCRÈTE :, À RETENIR :).

4. RÈGLE D'OR D'ESPACEMENT (MODÈLE À SUIVRE STRICTEMENT) :

# CHAPITRE 1 : LE TITRE DU CHAPITRE

## Premier Sous-Titre De Section

LE CONSTAT : Premier paragraphe court de 3 à 4 lignes. Bien aéré.

L'ACTION CONCRÈTE : Deuxième paragraphe court de 3 à 4 lignes. Se termine sans coller la suite.

## Deuxième Sous-Titre De Section

L'INVITATION : Troisième paragraphe court. Toujours précédé de deux sauts de ligne.
"""

# ── 1. PROMPT MAÎTRE ────────────────────────────────────────────────────────
def get_prompt_createur_system(type_contenu: str) -> str:
    return f"""Tu es un directeur éditorial d'élite.
Ta mission est de concevoir un PROMPT MAÎTRE très détaillé et très structuré pour un projet de type : {type_contenu.upper()}.

CONSIGNE DÉTAILLÉE :
Développe un brief complet qui servira de guide pour la rédaction.
Détaille l'objectif pédagogique, le public cible, le ton et les grands axes thématiques.
Rédige un brief riche de plusieurs paragraphes."""

def get_prompt_createur_user(sujet: str, type_contenu: str) -> str:
    return f"Format demandé : {type_contenu}\nSujet / Idée de départ :\n{sujet.strip()}\n\nConçois le prompt maître éditorial complet."

# ── 2. DÉCOMPOSITION ─────────────────────────────────────────────────────────
def get_decoupage_system(nb_points: int) -> str:
    return f"""Tu es un expert de la cartographie de connaissances.
Extrais et numérote EXACTEMENT {nb_points} points d'analyse et d'action numérotés de 1 à {nb_points}.
Ne fais aucune introduction ni conclusion, génère uniquement la liste numérotée (1., 2., ...)."""

def get_decoupage_user(prompt_maitre: str, nb_points: int) -> str:
    return f"""=== PROMPT MAÎTRE ===
{prompt_maitre.strip()}

MISSION : Décompose l'intégralité de ce sujet en EXACTEMENT {nb_points} points d'analyse et d'action numérotés."""

# ── 3. GÉNÉRATION DES BLOCS (1 SEULE PASSE STRUCTURÉE) ──────────────────────
def get_prompt_bloc_system(type_contenu: str) -> str:
    return f"""Tu es un auteur et rédacteur encyclopédique.
Ta mission est de rédiger une section complète, claire et très bien aérée basée sur le lot de points transmis.

{FORMAT_INSTRUCTION}

RÈGLES DE REDACTION :
- Couvre tous les points transmis de manière équilibrée, sans délayer artificiellement.
- Ne fais AUCUNE introduction générale du type "Dans ce bloc..." ni de conclusion de bloc.
- Respecte scrupuleusement les sauts de ligne doubles entre chaque sous-titre et chaque paragraphe.
"""

def get_prompt_bloc_user(prompt_maitre: str, tranche_points: str, numero_bloc: int, total_blocs: int) -> str:
    return f"""=== PROMPT MAÎTRE ===
{prompt_maitre.strip()}

=== TRANCHE DE POINTS À RÉDIGER (SECTION {numero_bloc}/{total_blocs}) ===
{tranche_points.strip()}

CONSIGNE :
Rédige la section {numero_bloc} en respectant strictement les règles d'espacement (sauts de ligne doubles obligatoires, # pour Chapitre, ## pour Sous-titre, paragraphes courts)."""

# ── 4. RACCORDS ET LISSAGE ───────────────────────────────────────────────────
def get_prompt_raccord_system() -> str:
    return f"""Tu es un éditeur littéraire.
Ta mission est de lisser la jonction entre la fin d'une section et le début de la suivante.

{FORMAT_INSTRUCTION}

RÈGLES :
- Fusionne les deux passages en un texte fluide de 400 mots environ sans répétitions.
- Conserve impérativement les sauts de ligne doubles et la structure aérée."""

def get_prompt_raccord_user(fin_bloc_a: str, debut_bloc_b: str) -> str:
    return f"""=== FIN SECTION PRÉCÉDENTE ===
{fin_bloc_a.strip()}

=== DÉBUT SECTION SUIVANTE ===
{debut_bloc_b.strip()}

MISSION :
Lisse ces deux passages en un texte fluide sans doublons et parfaitement aéré."""