"""Builds dist/<name>-<version>.nvda-addon from addon/, named from its manifest.

Usage: python build.py
An NVDA add-on is a zip file with manifest.ini at its root. The documentation is generated from
addon/doc/en/readme.md with a small converter, so no markdown package is needed. The repository's
LICENSE ships as COPYING.txt.
"""
import html
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, "addon")
DIST = os.path.join(HERE, "dist")


def manifest(key):
    for line in open(os.path.join(ADDON, "manifest.ini"), encoding="utf-8"):
        m = re.match(rf'{key}\s*=\s*"?([^"\n]+)"?', line)
        if m:
            return m.group(1).strip()
    raise SystemExit(f"no {key} in manifest.ini")


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"https://[^\s<]*[^\s<.,;:)]", r'<a href="\g<0>">\g<0></a>', text)
    return text


def markdown_to_html(md, title):
    out = [f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>{html.escape(title)}</title>\n</head>\n<body>"]
    paragraph = []
    list_kind = None

    def flush():
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph = []

    def close_list():
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            close_list()
            continue
        m = re.match(r"^(#+)\s+(.*)$", stripped)
        if m:
            flush()
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", stripped)
        if m:
            flush()
            kind = "ol" if stripped[0].isdigit() else "ul"
            if list_kind != kind:
                close_list()
                out.append(f"<{kind}>")
                list_kind = kind
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if list_kind:
            out[-1] = out[-1][:-5] + " " + inline(stripped) + "</li>"
            continue
        paragraph.append(stripped)
    flush()
    close_list()
    out.append("</body>\n</html>\n")
    return "\n".join(out)


def build():
    name, v, title = manifest("name"), manifest("version"), manifest("summary")
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, f"{name}-{v}.nvda-addon")
    docs = {}
    doc_root = os.path.join(ADDON, "doc")
    for lang in os.listdir(doc_root):
        md = os.path.join(doc_root, lang, "readme.md")
        if os.path.exists(md):
            docs[f"doc/{lang}/readme.html"] = markdown_to_html(open(md, encoding="utf-8").read(), title)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ADDON):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                # Markdown sources are rendered above; a licence notice ships as it is, whatever the case of its name.
                lower = name.lower()
                if lower.endswith(".pyc") or (lower.endswith(".md") and lower != "notice.md"):
                    continue
                path = os.path.join(dirpath, name)
                arc = os.path.relpath(path, ADDON).replace(os.sep, "/")
                zf.write(path, arc)
        for arc, content in docs.items():
            zf.writestr(arc, content)
        # The GPL text, under the name NVDA's add-on template gives it.
        zf.write(os.path.join(HERE, "LICENSE"), "COPYING.txt")
    size = os.path.getsize(target)
    print(f"built {target} ({size / 1024:.0f} KB)")
    return target


if __name__ == "__main__":
    build()
