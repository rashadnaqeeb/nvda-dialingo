"""Acceptance cases and corpus runner for the add-on's detector (addon/lib/mlang).

Usage: python harness.py <backend> [plain text file] [--strip]
Runs the acceptance cases, then the text paragraph by paragraph, listing every foreign run.
backend: els | fasttext | ensemble
HARNESS_NODICT=1 turns the spelling dictionary gate off.
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "addon", "lib"))

from mlang import recognizers  # noqa: E402
from mlang.detector import Detector as _Detector  # noqa: E402

FastTextBackend = recognizers.FastTextBackend
ELSBackend = recognizers.ELSBackend
EnsembleBackend = recognizers.EnsembleBackend
_shared = {}


def dictionary():
    if os.environ.get("HARNESS_NODICT"):
        return None
    if "dict" not in _shared:
        from mlang.dictionary import Dictionary
        _shared["dict"] = Dictionary()
    return _shared["dict"]


def Detector(backend, default="en", spoken=("en", "fr", "de"), mode="full"):
    return _Detector(backend, default, [s for s in spoken if s != default], dictionary(), mode)


def worded(runs):
    return [l for l, t in runs if any(c.isalpha() for c in t)]


# ---------------------------------------------------------------- acceptance

def acceptance(backend):
    A = Detector(backend, "en", ["en", "fr", "de"])
    B = Detector(backend, "en", ["en", "fr", "es"])
    C = Detector(backend, "en", ["en", "fr", "es"])
    C3 = Detector(backend, "en", ["en", "fr", "es", "it"])
    D = Detector(backend, "en", ["en", "es"])
    E = Detector(backend, "en", ["en", "es", "fr", "de"])
    R = Detector(backend, "en", ["en", "ru", "ar", "el", "ja", "zh", "ko"])
    cases = []

    def case(det, text, expect, mode="worded"):
        cases.append((det, text, expect, mode))

    case(A, "Bonjour tout le monde, comment allez-vous aujourd'hui?", ["fr"])
    case(A, "\"Well, mon cher,\" said the vicomte, \"your little princess is very nice.\"", [None, "fr", None])
    # Expectations list the runs that hold letters; a bare quote run does not count.
    case(A, "\"Cependant, mon cher,\" he remarked, examining his nails from a distance.", ["fr", None])
    for t in ["Pierre looked at Lorrain.", "Attendez", "Oui", "Pierre, said the vicomte."]:
        case(A, t, [None])
    case(A, "sentence: malgre la haute estime que je professe pour the Orthodox Russian army, j'avoue que votre victoire n'est pas des plus victorieuses", [None, "fr", None, "fr"])
    case(A, "Oui, oui, je suis là.", ["fr"])
    case(A, "tyler whitcomb , demain, je passerai chez le garagiste et je lui demanderai combien coûte la réparation de la voiture. Et je vous tiendrai au courant de sa réponse. Merci mille fois pour votre aide, vraiment. , 8:05 PM  message", [None, "fr", None])
    case(A, "Bonjour Pierre, comment vas-tu?", ["fr"])
    case(A, "\"How plainly all these young people wear their hearts on their sleeves!\" said Anna Mikhaylovna, pointing to Nicholas as he went out. \"Cousinage--dangereux voisinage;\"* she added.", [None, "fr", None])
    case(A, "\"Cependant, mon cher,\" he remarked, examining his nails from a distance and puckering the skin above his left eye, \"malgre la haute estime que je professe pour the Orthodox Russian army, j'avoue que votre victoire n'est pas des plus victorieuses.\"*", ["fr", None, "fr", None, "fr"])
    case(B, "\"Well, then, old chap, mon tres honorable Alphonse Karlovich,\" said Shinshin, laughing ironically and mixing the most ordinary Russian expressions with the choicest French phrases--which was a peculiarity of his speech. \"Vous comptez vous faire des rentes sur l'etat;* you want to make something out of your company?\"", [None, "fr", None])
    italian = "\"'Dieu me la donne, gare a qui la touche!'* They say he was very fine when he said that,\" he remarked, repeating the words in Italian: \"'Dio mi l'ha dato. Guai a chi la tocchi!'\""
    case(C, italian, ["fr", None])
    case(C3, italian, ["fr", None, "it"])
    for t in ["No", "OK", "Cancel", "Documents", "Send message", "Guardar", "60 sesenta", "Lesson 11 (32 points)", "Pierre looked at Lorrain."]:
        case(D, t, [None])
    for t in ["¿Tú eres Miguel? No, yo no soy Miguel.", "Hola, buenos días"]:
        case(D, t, ["es"])
    for t in ["Orange, la naranja", "Desk, el escritorio"]:
        case(D, t, "es", "last")
    for t in ["Documents", "Documents list", "Send message", "Si", "Orange", "Claude Code v2.1.37", "Claude Code", "claude-fable-5-1", "Sort options", "Sort Options", "Welcome to Claude Code", "Anna Pavlovna Scherer"]:
        case(E, t, [None])
    case(E, "Hola, buenos días", ["es"])
    for t in ["y", "o", "e", "a", "I", "ñ", "Y", "7", "?"]:
        case(D, t, [None])
    # Script mode: other scripts go by script alone, a lone borrowed letter stays.
    case(R, "Hello, мир и Привет всем!", [None, "ru"])
    case(R, "Say مرحبا بالعالم now", [None, "ar", None])
    case(R, "Ref.: U-0055 • Cat.: ε 0", [None])
    case(R, "日本語のテキストです", ["ja"])
    case(R, "你好世界", ["zh"])
    case(R, "안녕하세요 world", ["ko", None])
    case(R, "Windows10のアプリ", [None, "ja"])
    # A foreign script several configured languages write: its clauses are detected among them.
    RU = Detector(backend, "en", ["en", "ru", "uk", "bg"])
    case(RU, "Привет, как дела? Привіт, як справи у тебе сьогодні?", ["ru", "uk"])
    case(RU, "Сегодня хорошая погода. Днес времето е хубаво.", ["ru", "bg"])
    case(RU, "Тарас Шевченко написал много стихов о родине.", ["ru"])
    case(RU, "The sign said Добро пожаловать в наш город and nothing else.", [None, "ru", None])
    case(Detector(backend, "ru", ["ru", "en", "fr"]), "Он сказал: Je ne sais pas quoi faire, and then he left.", [None, "fr", "en"])
    # Scripts without case or spaces, their punctuation, and scripts the default writes too.
    case(Detector(backend, "en", ["en", "hi", "mr"]), "मैं आज बाज़ार जा रहा हूँ और मुझे बहुत भूख लगी है। मी आज बाजारात जात आहे आणि मला खूप भूक लागली आहे।", ["hi", "mr"])
    case(Detector(backend, "ar", ["ar", "fa"]), "أنا ذاهب إلى المدرسة اليوم مع أصدقائي، من امروز با دوستانم به مدرسه می‌روم و کتاب می‌خوانم؟", [None, "fa"])
    case(Detector(backend, "en", ["en", "ar", "fa"]), "هذا هو بيتي. این خانه من است و آن خانه تو است.", ["ar", "fa"])
    case(Detector(backend, "zh", ["zh", "ja"]), "今天天气很好。私は毎日日本語を勉強しています。", [None, "ja"])
    case(Detector(backend, "ja", ["ja", "zh"]), "今日は東京に行きました。我今天去商店买东西，然后回家做饭。", [None, "zh"])
    case(Detector(backend, "ja", ["ja", "zh"]), "東京に行きました。東京都庁。", [None])
    case(Detector(backend, "en", ["en", "sr", "ru"]), "Београд је главни и највећи град Србије. Москва является столицей России.", ["sr", "ru"])
    case(Detector(backend, "sr", ["sr", "ru"]), "Данас је леп дан и идем у продавницу да купим хлеб. Сегодня хорошая погода, и я иду в магазин.", [None, "ru"])

    passed = 0
    for det, text, expect, mode in cases:
        runs = det.tagged(text)
        got = worded(runs)
        if mode == "last":
            ok = runs[-1][0] == expect
        else:
            # A line with no letters has no worded run; it counts as untagged.
            ok = got == expect or (not got and expect == [None])
        passed += ok
        if not ok:
            print(f"  FAIL {text[:70]!r}\n       expected {expect} got {got} runs={[(l, t[:30]) for l, t in runs]}")
    # Tag distrust: a Russian tag on Latin text is dropped; a French tag on English clauses too.
    checks = [
        (A.verified("Search Results", "ru"), [None]),
        (A.verified("Résultats de recherche", "fr"), ["fr"]),
        (A.verified("About this result", "fr"), [None]),
        (A.verified("Steam Community, Communauté Steam", "fr"), [None, "fr"]),
        # A tag holds only where the text is in a script its language writes, both ways round.
        (Detector(backend, "ru", ["ru", "en"]).verified("Скачать файл в формате PDF бесплатно и без регистрации.", "en"), [None, "en", None]),
        (Detector(backend, "en", ["en", "ru"]).verified("Download the file in Word format for free, Пожалуйста.", "ru"), [None, "ru"]),
        (Detector(backend, "en", ["en", "ru"]).verified("Привет, как дела у тебя сегодня?", "ru"), ["ru"]),
    ]
    for runs, expect in checks:
        ok = worded(runs) == expect
        passed += ok
        if not ok:
            print(f"  FAIL verified: expected {expect} got {worded(runs)} runs={runs}")
    print(f"{backend.name}: {passed}/{len(cases) + len(checks)} acceptance cases pass")


# ---------------------------------------------------------------- corpus

def strip_accents(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def corpus(backend, path, limit=200_000, strip=False):
    raw = open(path, encoding="utf-8").read()
    body = raw[:limit]
    if strip:
        body = strip_accents(body)
        print("  (accents stripped)")
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    det = Detector(backend, "en", ["en", "fr", "de"])
    t0 = time.perf_counter()
    foreign = []
    slowest = 0.0
    for p in paragraphs:
        t1 = time.perf_counter()
        runs = det.tagged(p)
        slowest = max(slowest, time.perf_counter() - t1)
        for lang, text in runs:
            if lang:
                foreign.append((lang, text.strip()))
    total = time.perf_counter() - t0
    print(f"{backend.name}: {len(paragraphs)} paragraphs, {len(body)} chars, {total*1000:.0f} ms total, slowest paragraph {slowest*1000:.1f} ms, {det.calls} recognizer calls")
    print(f"  {len(foreign)} foreign runs:")
    for lang, text in foreign:
        print(f"    [{lang}] {text[:110]}")


if __name__ == "__main__":
    name = sys.argv[1]
    backend = recognizers.make(name)
    acceptance(backend)
    if len(sys.argv) > 2:
        corpus(backend, sys.argv[2], strip="--strip" in sys.argv)
