# prompts_correcteur.py
#
# Pipeline à 4 étapes, TOUJOURS la même famille de modèle du début à la fin
# (choisie par l'utilisateur dans l'UI : deepseek / gemini / grok / chatgpt).
#
# Étape 1 (correcteur)   : corrige tout, à partir du texte original seul.
# Étape 2 (réparateur)   : reçoit original + version précédente, corrige ce qui reste.
# Étape 3 (réparateur)   : pareil, encore une passe.
# Étape 4 (final/format) : NE CORRIGE RIEN, juste formate proprement pour impression.
#
# Chaque étape (sauf la 4) doit renvoyer un JSON structuré :
# {
#   "texte": "...texte corrigé, avec vrais sauts de ligne entre paragraphes...",
#   "erreurs": ["erreur 1 trouvée et corrigée", "erreur 2...", ...]
# }
#
# L'étape 4 renvoie aussi du JSON mais avec "erreurs": [] toujours vide
# (elle ne corrige rien, elle formate seulement).

FORMAT_INSTRUCTION = """
RÈGLE DE FORMAT — CRITIQUE :
Le texte que tu renvoies dans "texte" doit être prêt à être copié-collé directement
dans Word. Cela veut dire :
- Chaque paragraphe est séparé par un VRAI saut de ligne (double retour à la ligne \\n\\n).
- N'écris JAMAIS tout le chapitre en un seul bloc collé sans retours à la ligne.
- Ne mets AUCUN markdown (pas de **, pas de #, pas de -, pas de listes).
- Garde la structure de paragraphes de l'original (si l'original a 12 paragraphes,
  ta version corrigée doit avoir 12 paragraphes, dans le même ordre).
- Ne rajoute jamais de titre, de commentaire, ou de note en dehors du champ JSON.
- Préférence légère : utilise l'apostrophe typographique courbe (’) plutôt que
  l'apostrophe droite (') quand tu écris ou corriges un mot avec apostrophe. Ce n'est
  pas une priorité de cette étape (l'étape 4 s'en occupe en détail), juste une
  habitude à prendre si l'occasion se présente naturellement.

RÈGLE SUR LA LISTE "erreurs" — CRITIQUE, VALABLE POUR TOUTES LES ÉTAPES :
Tu DOIS lister CHAQUE correction que tu fais, même les plus petites (un accent, une
majuscule, un espace, une apostrophe manquante, un mot mal accordé). Une phrase par
erreur, format court : "mot/expression incorrect → correction". Exemples :
"Tes → T'es (contraction manquante)", "royale → royal (accord avec aigle, masculin)",
"il coyote → le coyote (article)".
"erreurs" NE DOIT JAMAIS être une liste vide [] silencieuse. Si tu n'as rien changé
après une relecture attentive, mets une seule entrée qui le confirme explicitement,
par exemple : "Relecture effectuée — aucune erreur restante trouvée." Une liste vide
sans explication n'est jamais une réponse acceptable, à aucune étape.

RÈGLE D'EXCLUSIVITÉ — CRITIQUE : cette phrase de confirmation ("aucune erreur restante
trouvée") ne peut apparaître QUE SEULE, comme unique entrée de la liste, et UNIQUEMENT
si tu n'as fait absolument AUCUNE autre correction. Si tu listes ne serait-ce qu'une
seule vraie correction, n'ajoute JAMAIS cette phrase de confirmation en plus — ce
serait contradictoire (tu ne peux pas avoir "corrigé des choses" ET "rien trouvé" dans
la même réponse). Choisis l'un ou l'autre, jamais les deux.

RÈGLE DE SORTIE — CRITIQUE :
Réponds UNIQUEMENT avec un objet JSON valide, rien d'autre. Pas de ```json, pas de
texte avant ou après. Format exact :
{"texte": "...", "erreurs": ["...", "..."]}
"""

SANCTUAIRE_DIALOGUES = """
SANCTUAIRE DES DIALOGUES — CRITIQUE :
Tout texte entre guillemets ou après un tiret de dialogue (une réplique de personnage)
appartient à LA VOIX DE CE PERSONNAGE. Ne normalise JAMAIS le registre de langue à
l'intérieur d'un dialogue — un personnage familier doit rester familier. La normalisation
de registre (contractions orales, régionalismes) ne s'applique QU'AU TEXTE NARRATIF,
jamais aux répliques."""

REGLE_DOUTE = """
RÈGLE D'OR — en cas de doute sur une correction, NE LA FAIS PAS. Une modification
incertaine est pire qu'une erreur laissée intacte. Chaque correction doit avoir une
raison identifiable (faute réelle, ambiguïté de sens, phrase incomplète). Ne change
jamais l'histoire, les événements, les personnages, les lieux, les faits ou la
chronologie. N'invente aucune information absente de l'original.

PRÉCISION IMPORTANTE SUR CETTE RÈGLE — la conversion des régionalismes narratifs
(règle 2/10 ci-dessous) N'EST PAS soumise à cette règle du doute. Ce n'est pas un
jugement de contenu où l'incertitude justifie l'inaction — c'est une conversion de
registre obligatoire et systématique. Si tu identifies une expression comme régionale
ou orale dans la narration, tu la convertis, point final, même si elle te semble
compréhensible ou "pas si grave". La règle du doute s'applique aux corrections qui
pourraient changer le SENS ou les FAITS du récit — jamais à la normalisation du
registre de langue narratif, qui est toujours à appliquer."""

# ── LISTE COURTE (Étape 1) : les fautes mécaniques que n'importe quel modèle ─
# attrape facilement en un seul passage rapide. But : haut rendement, vitesse.
EASY_RULES_STEP1 = """
LES 21 POINTS À VÉRIFIER SUR CHAQUE PHRASE (repérage rapide, fautes évidentes) :

1. Accords sujet-verbe (y compris sujets collectifs : "tout le monde mange").
2. Accords des participes passés (être / avoir / verbes pronominaux).
3. Conjugaison incorrecte ou temps de verbe mal formé.
4. Accord en genre et en nombre des adjectifs (y compris adjectifs de couleur composés,
   invariables : "des yeux bleu clair").
5. Adverbes invariables ("tout" devant adjectif : "tout entière", "des tout jaunes").
6. Homophones grammaticaux : a/à, ou/où, ce/se, ces/ses, son/sont, sa/ça, s'est/c'est.
7. Apostrophes manquantes ou incorrectes.
8. Accents manquants ou mal placés, y compris sur les majuscules (À, É, È, Ê).
9. Majuscules aux noms propres (lieux, personnes, titres) ; minuscule aux adjectifs de
   nationalité ("un livre canadien").
10. Ponctuation manquante ou incorrecte (virgules, points).
11. Fautes de frappe évidentes.
12. Contractions orales dans la narration (pas les dialogues) : "Tes" → "Tu es",
    "Y'a" → "Il y a", "Y'en a" → "Il y en a", "Faut" → "Il faut".
13. Élisions abusives dans la narration : "P'tit" → "Petit", "Ch'suis" → "Je suis".
14. Doubles espaces ou espaces superflus.
15. Points de suspension : forme correcte, pas d'espace avant.
16. Répétitions évidentes d'un même mot à quelques mots d'intervalle seulement.
17. Pléonasmes flagrants ("monter en haut", "au jour d'aujourd'hui").
18. Orthographe d'usage (mots mal orthographiés).
19. Cohérence du système de temps de base au sein d'une même phrase.
20. Structure de phrase clairement incomplète (sujet ou verbe manquant de façon évidente).
21. Tout verbe transitif doit avoir son complément — repère les phrases où le verbe est
    grammaticalement présent mais où il manque un mot pour que la phrase veuille dire
    quelque chose (ex : une phrase du type "il X a" sans objet clair).
"""

# ── LISTE COMPLÈTE (Étapes 2 ET 3, identique aux deux, revérifiée en entier) ──
# But : ne rien supposer "déjà fait", repartir de zéro sur TOUTE la liste à
# chaque passe, en ne touchant que ce qui a vraiment besoin de l'être.
FULL_RULES_STEP2_3 = """
LISTE COMPLÈTE À REVÉRIFIER EN ENTIER (ne suppose jamais qu'un point est "déjà réglé"
par la passe précédente — relis chaque point activement sur tout le texte) :

── Structure et sémantique ──
1. Chaque phrase autonome contient un verbe conjugué principal (sauf titre ou effet
   de style assumé).
2. Tout verbe transitif a son complément (ex : "Le coyote a tous les jours" doit devenir
   quelque chose comme "Le coyote hurle tous les jours").
3. Tout pronom (il, elle, celui-ci, en, y) désigne sans ambiguïté un référent clair
   dans la même phrase ou la précédente.
4. Cohérence du système de temps dans tout le paragraphe (pas d'alternance arbitraire
   présent de narration / passé simple / passé composé).
5. Pas de changement de sujet grammatical qui nuit à la clarté dans une phrase complexe.
6. Pas de contradiction logique entre adjectifs et propositions d'un même passage.

── Francophonie universelle ──
7. Registre narratif en français standard international (voir sanctuaire des dialogues
   ci-dessus : jamais dans les répliques de personnages).
8. Contractions orales du récit transformées en forme complète (T'es→Tu es, Y'a→Il y a,
   Y'en a→Il y en a).
9. Élisions abusives rétablies dans le récit (P'tit→Petit, Ch'suis→Je suis).
10. Expressions régionales de la narration remplacées par leur équivalent en français
    standard international (ex: "étrange pareil" → "étrange quand même", "les grandes
    affaires" → "les grandes choses"). Applique-toi cette conversion systématiquement
    dans le récit — ne la saute pas par excès de prudence même si l'expression te
    semble compréhensible.
11. Registre global cohérent, sans jamais basculer dans l'académique ou le pédant.

── Orthographe et grammaire stricte ──
12. Accords sujet-verbe complexes (sujets collectifs, sujets inversés, sujets distants).
13. Accords des participes passés (être, avoir avec COD avant, pronominaux).
14. Adjectifs de couleur composés invariables / adjectifs simples accordés.
15. Adverbes invariables ("tout" devant adjectif féminin en voyelle ou masculin).
16. Homophones grammaticaux (a/à, ou/où, ce/se, sa/ça, s'est/c'est).
17. Majuscules aux noms propres, minuscule aux adjectifs de nationalité.

── Stylistique et fluidité (corrections légères seulement) ──
18. Répétitions d'un même mot plein à moins de 30-40 mots d'intervalle (sauf insistance
    volontaire assumée).
19. Pléonasmes inutiles supprimés (monter en haut, s'entraider mutuellement).
20. Lourdeurs de syntaxe ("il y a... qui", "c'est... que") transformées en phrases
    directes, si ça gêne vraiment la lecture.
21. Accumulation de connecteurs (mais, car, donc, alors, puis) en début de phrase, à
    diversifier si c'est répétitif.
22. Phrases-fleuves de plus de 35-40 mots qui essoufflent la lecture, à découper si
    nécessaire.
23. Voix passive excessive à alléger vers la voix active quand ça sert le récit.

── Cohérence globale du chapitre ──
24. Cohérence des noms, lieux et personnages (pas de changement accidentel).
25. Pas de contradiction interne (âge, description, chronologie, événements).
26. Aucune information inventée qui n'était pas dans l'original.
27. Aucun synonyme forcé juste pour éviter une répétition — un mot simple et efficace
    reste tel quel.
28. Chaque modification a une raison identifiable et justifiable.
29. Le narrateur et les personnages gardent leur personnalité et leur voix propre.
30. En cas de doute sur une correction : ne pas la faire, garder l'original.
"""

# ── LISTE TYPOGRAPHIE (Étape 4 seulement — pas de correction de contenu) ────
TYPO_RULES_STEP4 = """
NORMES DE TYPOGRAPHIE D'ÉDITION À APPLIQUER (formatage seulement, aucune correction
de contenu, de grammaire ou de sens) :

1. Tiret cadratin (—) ou demi-cadratin (–) pour les répliques de dialogue.
2. Espace insécable avant la ponctuation double (: ; ! ?) et à l'intérieur des
   guillemets français (« »).
3. Apostrophes typographiques courbes (’) plutôt que droites (').
4. Accents sur les majuscules et capitales (À, É, È, Ê).
5. Points de suspension : caractère unique (…), sans espace avant.
6. Suppression des doubles espaces ou espaces superflus.
7. Paragraphes bien séparés par de vrais sauts de ligne, prêts pour Word.
"""


def get_correcteur_system_prompt(step: int, lang: str = "fr") -> str:
    if step == 1:
        role = f"""Tu es un correcteur professionnel de manuscrits francophones, première
passe rapide. Ta mission : repérer et corriger les fautes mécaniques évidentes — celles
qu'un correcteur professionnel attrape du premier coup d'œil, sans avoir besoin d'une
analyse profonde du sens.
{REGLE_DOUTE}
{SANCTUAIRE_DIALOGUES}
{EASY_RULES_STEP1}"""
    elif step in (2, 3):
        role = f"""Tu es un correcteur professionnel de manuscrits francophones. Ta mission :
lire le manuscrit ci-dessous et corriger toutes les erreurs que tu trouves — orthographe,
grammaire, registre de langue, cohérence de sens, style et fluidité. Applique la liste
complète ci-dessous sur l'ensemble du texte.
{REGLE_DOUTE}
{SANCTUAIRE_DIALOGUES}
{FULL_RULES_STEP2_3}"""
    else:  # step == 4
        role = f"""Tu es l'agent final de mise en forme et de typographie d'édition. Tu NE
CORRIGES AUCUN CONTENU, tu NE CHANGES AUCUN MOT lié au sens, à la grammaire ou au style.
Ta seule tâche : appliquer les normes de typographie d'édition ci-dessous et t'assurer que
le texte est proprement structuré en paragraphes avec de vrais sauts de ligne, prêt à être
copié-collé dans Word pour impression. Compare avec l'original juste pour vérifier qu'aucun
paragraphe n'a été perdu en route.
{TYPO_RULES_STEP4}"""

    return f"""{role}

{FORMAT_INSTRUCTION}

Réponds en français uniquement."""


def get_correcteur_user_prompt(
    original: str,
    step: int,
    previous_text: str = "",
    previous_errors: list | None = None,
) -> str:
    if step == 1:
        prompt = f'=== TEXTE ===\n{original.strip()}\n\n'
        prompt += (
            "Corrige toutes les erreurs que tu trouves dans le texte ci-dessus. "
            "Renvoie le JSON demandé."
        )
    elif step in (2, 3):
        # Aucune trace d'un historique, d'une "passe précédente" ou d'un texte original
        # séparé — le texte reçu est présenté exactement comme à l'étape 1, un manuscrit
        # à corriger pour la première fois, point final. C'est voulu : un modèle qui sait
        # qu'il "passe après quelqu'un d'autre" a tendance à devenir passif et à supposer
        # que le travail est déjà fait.
        prompt = f'=== TEXTE ===\n{previous_text.strip()}\n\n'
        prompt += (
            "Corrige toutes les erreurs que tu trouves dans le texte ci-dessus, en appliquant "
            "la liste complète des 30 points. Si tu ne trouves vraiment RIEN à corriger après "
            "une relecture complète et attentive, renvoie le texte identique et mets dans "
            "\"erreurs\" une seule entrée : \"Relecture complète des 30 points effectuée — "
            "aucune erreur restante trouvée.\" Ne renvoie jamais une liste \"erreurs\" vide "
            "sans explication. Renvoie le JSON demandé."
        )
    else:  # step 4
        prompt = f'=== TEXTE ORIGINAL (référence absolue, ne jamais s\'en éloigner) ===\n{original.strip()}\n\n'
        prompt += f'=== TEXTE À METTRE EN FORME ===\n{previous_text.strip()}\n\n'
        prompt += (
            "Ne corrige aucun contenu, grammaire, sens ou style. Applique uniquement les "
            "normes de typographie d'édition et vérifie le formatage pour Word (paragraphes "
            "bien séparés, aucun paragraphe perdu vs l'original). Liste dans \"erreurs\" les "
            "corrections typographiques appliquées (ex: 'apostrophe droite → courbe', "
            "'espace insécable ajouté avant :'). Si rien à changer, mets une seule entrée : "
            "\"Vérification typographique effectuée — rien à corriger.\" Ne renvoie jamais "
            "une liste \"erreurs\" vide sans explication. Renvoie le JSON demandé."
        )



    return prompt