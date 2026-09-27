"""Dataset evaluation: switch rates over a directory of <kind>/<lang>.txt files.

Usage: python dataset_eval.py <backend> <dataset root> [configured, default fr,es] [--default L] [--limit N] [--show N]
    [--case title|upper]
A line in the default language (English unless --default names another) with any tag is a false switch; a line
in a configured language is a hit when its own language is tagged. --case recases every line as a headline: each word
capitalized, or all in capitals.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness  # noqa: E402
from mlang import recognizers  # noqa: E402


def capitalized(line):
    def cap(token):
        for i, c in enumerate(token):
            if c.isalpha():
                return token[:i] + c.upper() + token[i + 1:]
        return token
    return " ".join(cap(t) for t in line.split(" "))


CASES = {"title": capitalized, "upper": str.upper}


def main():
    name, root = sys.argv[1], sys.argv[2]
    configured = ["fr", "es"]
    default = "en"
    limit = None
    show = 15
    recase = None
    args = sys.argv[3:]
    i = 0
    while i < len(args):
        if args[i] == "--limit":
            limit = int(args[i + 1]); i += 2
        elif args[i] == "--default":
            default = args[i + 1]; i += 2
        elif args[i] == "--case":
            recase = CASES[args[i + 1]]; i += 2
        elif args[i] == "--show":
            show = int(args[i + 1]); i += 2
        else:
            configured = args[i].split(","); i += 1
    backend = recognizers.make(name)
    det = harness.Detector(backend, default, [default] + configured)
    files = []
    for dirpath, _, names in os.walk(root):
        for n in sorted(names):
            if n.endswith(".txt") and n[:-4] in [default] + configured:
                files.append(os.path.join(dirpath, n))
    print(f"backend {name}, default {default}, configured {configured}")
    for path in sorted(files):
        lang = os.path.basename(path)[:-4]
        lines = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
        if limit:
            lines = lines[:limit]
        if recase:
            lines = [recase(l) for l in lines]
        switched = hits = 0
        misses = []
        t0 = time.perf_counter()
        for line in lines:
            runs = det.tagged(line)
            tags = {l for l, t in runs if l}
            if tags:
                switched += 1
            if lang in tags:
                hits += 1
            if lang == default and tags:
                misses.append("".join(f"[{l}]{t}" if l else t for l, t in runs))
        ms = (time.perf_counter() - t0) * 1000
        rel = os.path.relpath(path, root).replace("\\", "/")
        pct = lambda n: f"{100 * n / max(1, len(lines)):.1f}%"
        print(f"=== {rel}: {len(lines)} lines, switched {pct(switched)}, own language tagged {pct(hits)}, {ms:.0f} ms")
        for m in misses[:show]:
            print(f"  false switch: {m[:120]}")


if __name__ == "__main__":
    main()
