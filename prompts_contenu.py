# prompts_contenu.py

FORMAT_INSTRUCTION = """
RÈGLES STRICTES DE STRUCTURE VISUELLE ET FORMATAGE (LIVRE & IMPRESSION) :

1. USAGE EXCLUSIF DES MAJUSCULES (CRUCIAL) :
   - Les MAJUSCULES sont STRICTEMENT RÉSERVÉES aux TITRES et SOUS-TITRES.
   - INTERDICTION ABSOLUE d'écrire des phrases, des mots d'emphase ou des étiquettes en MAJUSCULES au milieu ou au début des paragraphes.
   - Dans le corps du texte, utilise une typographie normale (Casse de phrase avec première lettre en majuscule seulement).

2. ISOLEMENT TOTAL DES TITRES ET SOUS-TITRES :
   - Chaque titre ou sous-titre doit être ISOLÉ sur sa propre ligne, séparé du texte précédent et suivant par un SAUT DE LIGNE DOUBLE.
   - INTERDICTION de coller deux titres ensemble (ex: NE FAIS PAS "PARTIE 1 CHAPITRE 1", écris "PARTIE 1" puis saut de ligne, puis "CHAPITRE 1").
   - INTERDICTION d'accoler un titre directement au début d'un paragraphe.

3. PAS DE MARKDOWN NI D'ÉTIQUETTES :
   - N'utilise AUCUNE balise Markdown (pas de #, ##, ### ni **).
   - INTERDICTION STRICTE de répéter des préfixes comme "LE CONSTAT :", "L'ACTION CONCRÈTE :", "L'INVITATION :" au début des paragraphes.

4. MODÈLE À SUIVRE STRICTEMENT :

TITRE DU CHAPITRE EN MAJUSCULES

SOUS-TITRE DE SECTION EN MAJUSCULES

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
Ta mission est de rédiger un volume EXTRÊMEMENT DÉTAILLÉ, très LONG ET très DENSE d'environ 3 000 à 4 000 mots.
Aide-toi des points d'analyse et d'action fournis comme simple fil conducteur pour rédiger un texte littéraire continu et structuré sur le sujet.

{FORMAT_INSTRUCTION}

RÈGLES DE RÉDACTION :
- Seuls les titres et sous-titres sont en MAJUSCULES. Le reste du texte est rédigé normalement.
- Isole chaque titre/sous-titre sur sa propre ligne avec des sauts de ligne.
- Ne fais AUCUNE introduction générale du type "Dans ce bloc..." ni de conclusion de bloc.
- Écris sans aucun symbole Markdown (#, ##, **).
- Rédige directement le texte de manière fluide, sans préfixes répétitifs.
"""

def get_prompt_bloc_user(prompt_maitre: str, tranche_points: str, numero_bloc: int, total_blocs: int) -> str:
    return f"""=== PROMPT MAÎTRE ===
{prompt_maitre.strip()}

=== TRANCHE DE POINTS À RÉDIGER (SECTION {numero_bloc}/{total_blocs}) ===
{tranche_points.strip()}

CONSIGNE :
Rédige la section {numero_bloc} (titres en MAJUSCULES isolés sur leur propre ligne, pas de majuscules dans les paragraphes, pas de Markdown, rédaction fluide)."""

# ── 4. RACCORDS ET LISSAGE ───────────────────────────────────────────────────
def get_prompt_raccord_system() -> str:
    return f"""Tu es un éditeur littéraire.
Ta mission est de lisser la jonction entre la fin d'une section et le début de la suivante.

{FORMAT_INSTRUCTION}

RÈGLES :
- Fusionne les deux passages en un texte fluide de 400 mots environ sans répétitions.
- Seuls les titres/sous-titres restent en MAJUSCULES sur leur propre ligne.
- Conserve l'absence de Markdown."""

def get_prompt_raccord_user(fin_bloc_a: str, debut_bloc_b: str) -> str:
    return f"""=== FIN SECTION PRÉCÉDENTE ===
{fin_bloc_a.strip()}

=== DÉBUT SECTION SUIVANTE ===
{debut_bloc_b.strip()}

MISSION :
Lisse ces deux passages en un texte fluide sans doublons."""