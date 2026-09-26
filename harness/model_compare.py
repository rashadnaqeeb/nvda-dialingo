"""Compares candidate fastText model files on what the detector needs from a recognizer.

Usage: python model_compare.py <model.ftz> [more models...]
For each model: how many probe words are unknown (the model answers as it does for an empty string),
the acceptance count, and the switch and hit rates over the lingua and NVDA-string datasets.
"""
import contextlib
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "addon", "lib"))
from mlang import recognizers  # noqa: E402

PROBE = ["no", "No", "yes", "the", "army", "Oui", "oui", "Si", "si", "La", "la", "Desk", "desk", "Miguel", "naranja",
         "merci", "bonjour", "Bonjour", "Orange", "orange", "hola", "Hola", "cat", "hello", "world", "Dieu", "malgre",
         "casa", "maison", "Haus", "gracias", "danke", "please", "por", "favor", "avec", "sans", "und", "oder"]


def unknown_words(model):
    empty = model.probs("")[:5]
    return [w for w in PROBE if model.probs(w)[:5] == empty]


def run(cmd, env):
    out = subprocess.run([sys.executable] + cmd, capture_output=True, text=True, env=env, cwd=os.path.join(HERE, ".."))
    return out.stdout + out.stderr


def main():
    for path in sys.argv[1:]:
        path = os.path.abspath(path)
        print(f"===== {path} ({os.path.getsize(path) / 1024:.0f} KB)")
        model = recognizers.FastTextBackend(path)
        unknown = unknown_words(model)
        print(f"unknown probe words: {len(unknown)}/{len(PROBE)}: {' '.join(unknown)}")
        env = dict(os.environ, MLANG_MODEL=path, PYTHONUTF8="1")
        text = run(["harness/harness.py", "fasttext"], env)
        print([line for line in text.splitlines() if "acceptance cases" in line][0])
        for root, langs in (("datasets/lingua", "fr,es"), ("datasets/ui-strings", "fr,es,de,it,pt")):
            text = run(["harness/dataset_eval.py", "fasttext", root, langs, "--show", "0"], env)
            for line in text.splitlines():
                if line.startswith("==="):
                    parts = line.split(":")
                    name = parts[0][4:]
                    rest = parts[1].split(",")
                    print(f"  {name:22} {rest[1].strip():16} {rest[2].strip()}")


if __name__ == "__main__":
    main()
