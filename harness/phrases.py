# Acceptance phrases. Each entry: (text, expected)
# expected is a short human note on what the detector should do.
PHRASES = [
    # Must never switch (default English), Spanish/French/German configured
    ("No", "stay en"),
    ("OK", "stay en"),
    ("Cancel", "stay en"),
    ("Documents", "stay en"),
    ("Documents list", "stay en"),
    ("Send message", "stay en"),
    ("Guardar", "stay en (one word, no neighbor)"),
    ("60 sesenta", "stay en by rules; ideally es"),
    ("Lesson 11 (32 points)", "stay en"),
    ("Pierre looked at Lorrain.", "stay en"),
    ("Pierre, said the vicomte.", "stay en"),
    ("Attendez", "stay en"),
    ("Oui", "stay en"),
    ("Si", "stay en"),
    ("Orange", "stay en"),
    ("Claude Code v2.1.37", "stay en"),
    ("Claude Code", "stay en"),
    ("claude-fable-5-1", "stay en"),
    ("Sort options", "stay en"),
    ("Welcome to Claude Code", "stay en"),
    ("Anna Pavlovna Scherer", "stay en"),
    ("Sort options  button  subMenu", "stay en (reader words)"),
    ("submenu", "stay en"),
    ("button subMenu", "stay en"),
    # Must switch whole
    ("Hola, buenos días", "es"),
    ("¿Tú eres Miguel? No, yo no soy Miguel.", "es"),
    ("Bonjour tout le monde, comment allez-vous aujourd'hui?", "fr"),
    ("Oui, oui, je suis là.", "fr"),
    ("Bonjour Pierre, comment vas-tu?", "fr"),
    ("Buenos días a todos, ¿cómo estás hoy?", "es"),
    # Last run Spanish
    ("Orange, la naranja", "en then es"),
    ("Desk, el escritorio", "en then es"),
    ("la naranja", "es"),
    ("el escritorio", "es"),
    # Clauses
    ("mon cher,", "fr"),
    ("Cependant, mon cher,", "fr"),
    ("said the vicomte,", "en"),
    ("your little princess is very nice.", "en"),
    ("he remarked, examining his nails from a distance.", "en"),
    ("malgre la haute estime que je professe pour the Orthodox Russian army,", "fr with en tail"),
    ("malgre la haute estime que je professe pour", "fr (unaccented)"),
    ("the Orthodox Russian army,", "en"),
    ("j'avoue que votre victoire n'est pas des plus victorieuses.", "fr"),
    ("ma chere", "fr (unaccented, scored 0.73 by the reference recognizer)"),
    ("Cousinage--dangereux voisinage;", "fr"),
    ("Vous comptez vous faire des rentes sur l'etat;", "fr (unaccented)"),
    ("Dieu me la donne, gare a qui la touche!", "fr"),
    ("Dio mi l'ha dato. Guai a chi la tocchi!", "it (not configured -> stay en)"),
    ("mon tres honorable Alphonse Karlovich,", "fr-ish, names"),
    # Tagged French page that is really English
    ("About this result", "en"),
    ("Search Results", "en"),
    ("Résultats de recherche", "fr"),
    ("Communauté Steam", "fr"),
    ("Steam Community,", "en"),
    # Single chars, never guessed
    ("y", "never"),
    ("o", "never"),
    ("a", "never"),
]

# The longest full-line examples for timing and whole-line behavior.
LINES = [
    "\"Well, mon cher,\" said the vicomte, \"your little princess is very nice, very nice indeed, quite French.\"",
    "\"Cependant, mon cher,\" he remarked, examining his nails from a distance and puckering the skin above his left eye, \"malgre la haute estime que je professe pour the Orthodox Russian army, j'avoue que votre victoire n'est pas des plus victorieuses.\"*",
    "\"How plainly all these young people wear their hearts on their sleeves!\" said Anna Mikhaylovna, pointing to Nicholas as he went out. \"Cousinage--dangereux voisinage;\"* she added.",
]
