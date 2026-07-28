# prompts_contenu.py

FORMAT_INSTRUCTION = """
RÈGLES STRICTES DE STRUCTURE VISUELLE ET FORMATAGE (LIVRE & IMPRESSION) :

1. PAS DE MARKDOWN :
   - N'utilise AUCUNE balise Markdown (interdiction absolue d'utiliser #, ##, ### ou **).

2. TITRES ET SOUS-TITRES EN MAJUSCULES :
   - Écris tous les titres principaux et sous-titres EN MAJUSCULES UNIQUEMENT.
   - Place chaque titre/sous-titre sur sa propre ligne.

3. RÉDACTION NATURELLE DES PARAGRAPHES :
   - Rédige des paragraphes fluides, naturels et bien aérés.
   - INTERDICTION STRICTE de répéter des étiquettes ou préfixes comme "LE CONSTAT :", "L'ACTION CONCRÈTE :", "L'INVITATION :" au début des paragraphes. Écris directement le texte.

4. MODÈLE À SUIVRE STRICTEMENT :

TITRE DU CHAPITRE EN MAJUSCULES

Sous-Titre De Section En Majuscules

Premier paragraphe fluide qui développe la première idée avec clarté.

Deuxième paragraphe court qui enchaîne naturellement sur la suite.
"""

# ── 1. PROMPT MAÎTRE ────────────────────────────────────────────────────────
def get_prompt_createur_system(type_contenu: str) -> str:
    return f"""Tu es un directeur éditorial d'élite.
Ta mission est de concevoir un PROMPT MAÎTRE très détaillé et très structuré pour un projet de type : {type_contenu.upper()}.

CONSIGNE DÉTAILLÉE :
Développe un brief complet qui servira de guide pour la rédaction.
Détaille l'objectif pédagogique, le public cible, le ton et les grands axes thématiques.
Rédige un brief riche de plusieurs paragraphes.
Indique tous les titres et sous-titres en MAJUSCULES sans utiliser de Markdown, ni d'étiquettes répétitives."""

def get_prompt_createur_user(sujet: str, type_contenu: str) -> str:
    return f"Format demandé : {type_contenu}\nSujet / Idée de départ :\n{sujet.strip()}\n\nConçois le prompt maître éditorial complet (titres en MAJUSCULES, pas de Markdown)."

# ── 2. DÉCOMPOSITION ─────────────────────────────────────────────────────────
def get_decoupage_system(nb_points: int) -> str:
    return f"""Tu es un expert de la cartographie de connaissances.
Extrais et numérote EXACTEMENT {nb_points} points d'analyse et d'action numérotés de 1 à {nb_points}.
Ne fais aucune introduction ni conclusion, génère uniquement la liste numérotée (1., 2., ...)."""

def get_decoupage_user(prompt_maitre: str, nb_points: int) -> str:
    return f"""=== PROMPT MAÎTRE ===
{prompt_maitre.strip()}

MISSION : Décompose l'intégralité de ce sujet en EXACTEMENT {nb_points} points d'analyse et d'action numérotés."""

# ── 3. GÉNÉRATION DES BLOCS ──────────────────────────────────────────────────
def get_prompt_bloc_system(type_contenu: str) -> str:
    return f"""Tu es un auteur et rédacteur encyclopédique.
Ta mission est de rédiger une section complète et claire basée sur le lot de points transmis.

{FORMAT_INSTRUCTION}

RÈGLES DE RÉDACTION :
- Couvre tous les points transmis de manière équilibrée.
- Ne fais AUCUNE introduction générale du type "Dans ce bloc..." ni de conclusion de bloc.
- Écris les titres et sous-titres en MAJUSCULES, sans aucun symbole Markdown (#, ##, **).
- Rédige directement le texte sans ajouter de préfixes répétitifs (pas de "LE CONSTAT :", etc.).
"""

def get_prompt_bloc_user(prompt_maitre: str, tranche_points: str, numero_bloc: int, total_blocs: int) -> str:
    return f"""=== PROMPT MAÎTRE ===
{prompt_maitre.strip()}

=== TRANCHE DE POINTS À RÉDIGER (SECTION {numero_bloc}/{total_blocs}) ===
{tranche_points.strip()}

CONSIGNE :
Rédige la section {numero_bloc} (titres en MAJUSCULES uniquement, pas de Markdown, rédaction fluide)."""

# ── 4. RACCORDS ET LISSAGE ───────────────────────────────────────────────────
def get_prompt_raccord_system() -> str:
    return f"""Tu es un éditeur littéraire.
Ta mission est de lisser la jonction entre la fin d'une section et le début de la suivante.

{FORMAT_INSTRUCTION}

RÈGLES :
- Fusionne les deux passages en un texte fluide de 400 mots environ sans répétitions.
- Conserve les titres en MAJUSCULES et l'absence de Markdown."""

def get_prompt_raccord_user(fin_bloc_a: str, debut_bloc_b: str) -> str:
    return f"""=== FIN SECTION PRÉCÉDENTE ===
{fin_bloc_a.strip()}

=== DÉBUT SECTION SUIVANTE ===
{debut_bloc_b.strip()}

MISSION :
Lisse ces deux passages en un texte fluide sans doublons."""