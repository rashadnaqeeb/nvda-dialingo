"""Wrapped lines read alone, in context, and as part of their whole paragraph: letters read in the wrong language.

Usage: python line_eval.py <backend> <lingua root> <default> <other> [--paragraphs N] [--widths 40,60,80,100]
Paragraphs of five sentences from <lingua root>/sentences are built four ways: all in the default language, all
in the other, the default's with one sentence of the other in the middle, and the other way round. Each is
wrapped at every width, and every line is read three ways: alone (Detector.tagged), in context
(Detector.in_context, as the add-on reads a line at the caret or in say all), and sliced out of its whole
paragraph's detection, the most context there is. A letter of the other language's sentences should be
tagged with it, and a letter of the default's left untagged.
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness  # noqa: E402
from mlang import recognizers  # noqa: E402
from mlang.detector import slice_runs  # noqa: E402

MODES = ("alone", "context", "paragraph")


def wrap(text, width):
    """Greedy word wrap, as (start, end) spans of `text`, each holding the space it broke at, as a line of an
    edit control or of browse mode does."""
    spans = []
    start = 0
    n = len(text)
    while start < n:
        while start < n and text[start] == " ":
            start += 1
        if start >= n:
            break
        if n - start <= width:
            spans.append((start, n))
            break
        cut = text.rfind(" ", start, start + width + 1)
        if cut <= start:
            cut = text.find(" ", start + width)
            cut = n if cut < 0 else cut
        spans.append((start, min(n, cut + 1)))
        start = cut + 1
    return spans


def paragraphs(root, default, other, count):
    """(kind, text, truth): truth is the language of each character, '' between sentences."""
    def load(lang):
        path = os.path.join(root, "sentences", lang + ".txt")
        return [l.strip() for l in open(path, encoding="utf-8") if l.strip()]

    rnd = random.Random(7)
    pools = {default: load(default), other: load(other)}
    out = []

    def build(kind, langs):
        text, truth = "", []
        for lang in langs:
            s = rnd.choice(pools[lang])
            if text:
                text += " "
                truth.append("")
            text += s
            truth += [lang] * len(s)
        out.append((kind, text, truth))

    for _ in range(count):
        build(default, [default] * 5)
        build(other, [other] * 5)
        build(f"{default} with {other}", [default, default, other, default, default])
        build(f"{other} with {default}", [other, other, default, other, other])
    return out


def read(det, mode, text, start, end):
    line = text[start:end]
    if mode == "alone":
        return det.tagged(line)
    if mode == "context":
        return det.in_context(line, text, start)
    return slice_runs(det.tagged(text), start, end)


def main():
    name, root, default, other = sys.argv[1:5]
    count = 40
    widths = (40, 60, 80, 100)
    args = sys.argv[5:]
    i = 0
    while i < len(args):
        if args[i] == "--paragraphs":
            count = int(args[i + 1]); i += 2
        elif args[i] == "--widths":
            widths = tuple(int(w) for w in args[i + 1].split(",")); i += 2
        else:
            raise SystemExit(f"unknown argument {args[i]}")
    backend = recognizers.make(name)
    det = harness.Detector(backend, default, [default, other])
    built = paragraphs(root, default, other, count)
    print(f"backend {name}, default {default}, configured {other}, {count} paragraphs of each kind, widths {widths}")
    for mode in MODES:
        stats = {}
        slowest = 0.0
        t0 = time.perf_counter()
        for kind, text, truth in built:
            for width in widths:
                for start, end in wrap(text, width):
                    t = time.perf_counter()
                    runs = read(det, mode, text, start, end)
                    slowest = max(slowest, time.perf_counter() - t)
                    s = stats.setdefault(kind, [0, 0, 0, 0])  # letters, wrong letters, lines, lines wrong
                    position = start
                    wrong = False
                    for lang, piece in runs:
                        got = other if lang else default
                        for ch in piece:
                            want = truth[position]
                            position += 1
                            if ch.isalpha() and want:
                                s[0] += 1
                                if got != want:
                                    s[1] += 1
                                    wrong = True
                    s[2] += 1
                    s[3] += wrong
        ms = (time.perf_counter() - t0) * 1000
        letters = sum(s[0] for s in stats.values())
        wrong = sum(s[1] for s in stats.values())
        lines = sum(s[2] for s in stats.values())
        bad = sum(s[3] for s in stats.values())
        print(f"=== {mode}: {100 * wrong / letters:.2f}% of letters wrong, {bad} of {lines} lines with a wrong letter, "
              f"{ms:.0f} ms, slowest line {slowest * 1000:.1f} ms")
        for kind, s in stats.items():
            print(f"  {kind}: {100 * s[1] / s[0]:.2f}% of letters wrong, {s[3]} of {s[2]} lines")


if __name__ == "__main__":
    main()
