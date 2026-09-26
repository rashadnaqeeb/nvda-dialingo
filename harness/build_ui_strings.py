"""Turn NVDA's nvda.po translation files into per-language UI string samples: en.txt from msgid, <lang>.txt from msgstr."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
base = os.path.join(HERE, "..", "datasets", "ui-strings")


def parse(path):
    pairs = []
    msgid = msgstr = None
    cur = None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("msgid "):
            if msgid is not None and msgstr:
                pairs.append((msgid, msgstr))
            msgid = line[6:].strip('"')
            msgstr = ""
            cur = "id"
        elif line.startswith("msgstr "):
            msgstr = line[7:].strip('"')
            cur = "str"
        elif line.startswith('"') and cur:
            if cur == "id":
                msgid += line.strip('"')
            else:
                msgstr += line.strip('"')
        elif not line.strip():
            if msgid is not None and msgstr:
                pairs.append((msgid, msgstr))
            msgid = msgstr = None
            cur = None
    return pairs


def clean(s):
    s = s.replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')
    s = re.sub(r"%\([^)]*\)[sdf]|\{[^}]*\}|%[sdf]|&", "", s)
    return re.sub(r"\s+", " ", s).strip()


en = set()
for lang in ["es", "fr", "de", "it", "pt_BR"]:
    pairs = parse(os.path.join(base, "po", lang + ".po"))
    out = []
    for i, s in pairs:
        i2, s2 = clean(i), clean(s)
        if len(i2) < 3 or len(s2) < 3 or i2 == s2 or len(i2) > 200 or len(s2) > 200:
            continue
        if not any(c.isalpha() for c in i2):
            continue
        en.add(i2)
        out.append(s2)
    code = lang.split("_")[0]
    with open(os.path.join(base, code + ".txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(dict.fromkeys(out)) + "\n")
    print(lang, len(pairs), "pairs ->", len(set(out)), "lines")
with open(os.path.join(base, "en.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(sorted(en)) + "\n")
print("en", len(en), "lines")
