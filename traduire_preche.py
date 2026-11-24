#!/usr/bin/env python3
"""
Traduit une prêche audio (MP3) dans plusieurs langues, avec une voix.

Pipeline 100 % gratuit :
  1. Transcription  : faster-whisper (local, pas de clé)
  2. Traduction     : Google Traduction via deep-translator (pas de clé)
                      ou Gemini (clé gratuite, meilleure qualité)
  3. Voix           : edge-tts (voix neuronales Microsoft, pas de clé)

Exemple :
  python traduire_preche.py preche.mp3
  python traduire_preche.py preche.mp3 --langues es zh ru hi --modele medium
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Configuration des langues
# --------------------------------------------------------------------------
# code court -> (code Google Traduction, nom, voix edge-tts par défaut)
LANGUES = {
    "zh": ("zh-CN", "chinois", "zh-CN-YunxiNeural"),
    "es": ("es", "espagnol", "es-MX-JorgeNeural"),
    "ru": ("ru", "russe", "ru-RU-DmitryNeural"),
    "hi": ("hi", "hindi", "hi-IN-MadhurNeural"),
    # Langues supplémentaires possibles :
    "en": ("en", "anglais", "en-US-GuyNeural"),
    "fr": ("fr", "français", "fr-FR-HenriNeural"),
    "pt": ("pt", "portugais", "pt-BR-AntonioNeural"),
    "ar": ("ar", "arabe", "ar-SA-HamedNeural"),
}
# Toutes les autres langues de Google Traduction (langues.json : code Google,
# nom anglais, voix Microsoft disponibles ; liste vide = texte seulement).
def _charger_langues() -> dict:
    import json
    try:
        return json.loads(Path(__file__).with_name("langues.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


TOUTES = _charger_langues()
for _code, _l in TOUTES.items():
    if _code not in LANGUES:
        LANGUES[_code] = (_l["google"], _l["nom"], _l["voix"][0] if _l["voix"] else None)
LANGUES_PAR_DEFAUT = ["zh", "es", "ru"]

# Google Traduction gratuit refuse les textes de plus de ~5000 caractères.
TAILLE_MORCEAU = 4000


# --------------------------------------------------------------------------
# 1. Transcription
# --------------------------------------------------------------------------
def lire_audio(audio: Path):
    """Décode l'audio en 16 kHz mono avec ffmpeg (plus fiable que PyAV)."""
    import shutil
    import subprocess

    import numpy as np

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # ffmpeg fourni par le paquet pip imageio-ffmpeg (aucune installation système)
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    brut = subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(audio),
         "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(brut, np.int16).astype(np.float32) / 32768.0


def transcrire(audio: Path, modele: str, langue_source: str) -> str:
    from faster_whisper import WhisperModel

    print(f"[1/3] Transcription de {audio.name} (modèle Whisper « {modele} »)…")
    print("      La première fois, le modèle est téléchargé (quelques centaines de Mo).")
    model = WhisperModel(modele, device="auto", compute_type="int8",
                         cpu_threads=os.cpu_count() or 4)
    segments, info = model.transcribe(
        lire_audio(audio), language=langue_source, vad_filter=True, beam_size=5
    )
    morceaux = []
    for seg in segments:
        morceaux.append(seg.text.strip())
        minutes, secondes = divmod(int(seg.end), 60)
        print(f"\r      … {minutes:02d}:{secondes:02d} / "
              f"{int(info.duration) // 60:02d}:{int(info.duration) % 60:02d}",
              end="", flush=True)
    print()
    return " ".join(morceaux)


# --------------------------------------------------------------------------
# 2. Traduction
# --------------------------------------------------------------------------
def decouper(texte: str, taille: int = TAILLE_MORCEAU) -> list[str]:
    """Découpe le texte en morceaux sans couper au milieu d'une phrase."""
    phrases = re.split(r"(?<=[.!?。！？])\s+", texte.strip())
    morceaux, courant = [], ""
    for phrase in phrases:
        # Une phrase plus longue que la limite : on la coupe sur les espaces.
        while len(phrase) > taille:
            coupe = phrase.rfind(" ", 0, taille)
            coupe = coupe if coupe > 0 else taille
            if courant:
                morceaux.append(courant)
                courant = ""
            morceaux.append(phrase[:coupe])
            phrase = phrase[coupe:].strip()
        if len(courant) + len(phrase) + 1 > taille and courant:
            morceaux.append(courant)
            courant = phrase
        else:
            courant = f"{courant} {phrase}".strip()
    if courant:
        morceaux.append(courant)
    return morceaux


def traduire_gtx(texte: str, source: str, cible: str) -> str:
    """Google Traduction via translate.googleapis.com (gratuit, sans clé)."""
    import requests

    url = "https://translate.googleapis.com/translate_a/single"
    resultat = []
    for morceau in decouper(texte, 2500):
        for essai in range(3):
            try:
                r = requests.post(
                    url,
                    params={"client": "gtx", "sl": source, "tl": cible, "dt": "t"},
                    data={"q": morceau},
                    timeout=60,
                )
                r.raise_for_status()
                resultat.append("".join(s[0] for s in r.json()[0] if s[0]))
                break
            except Exception as e:
                if essai == 2:
                    raise
                attente = 10 * (essai + 1)  # 10 s, 20 s
                print(f"      Erreur ({e}), nouvel essai dans {attente} s…")
                time.sleep(attente)
        time.sleep(2)
    return " ".join(resultat)


def traduire_google(texte: str, source: str, cible: str) -> str:
    from deep_translator import GoogleTranslator

    traducteur = GoogleTranslator(source=source, target=cible)
    resultat = []
    for i, morceau in enumerate(decouper(texte), 1):
        for essai in range(4):
            try:
                resultat.append(traducteur.translate(morceau))
                break
            except Exception as e:  # réseau / limite temporaire
                if essai == 3:
                    raise
                print(f"      Erreur ({e}), nouvel essai…")
                time.sleep(2 ** (essai + 1))
        time.sleep(0.5)  # rester poli avec le service gratuit
    return " ".join(resultat)


_MODELE_GEMINI = None


def _gemini(client, modele: str, prompt: str) -> str:
    """Un appel Gemini avec une réflexion « faible » : 10 fois plus rapide,
    et largement suffisant pour traduire."""
    from google.genai import types

    try:
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="low"))
        return client.models.generate_content(model=modele, contents=prompt, config=config).text
    except Exception as e:
        if "INVALID_ARGUMENT" not in str(e):
            raise
        # Modèle qui ne gère pas ce réglage : appel normal.
        return client.models.generate_content(model=modele, contents=prompt).text


def modele_gemini(client) -> str:
    """Choisit le modèle Gemini « flash » le plus récent qui répond vite.

    Les noms de modèles changent souvent : on les découvre au lieu de les figer.
    La variable GEMINI_MODELE permet d'en imposer un."""
    global _MODELE_GEMINI
    if _MODELE_GEMINI:
        return _MODELE_GEMINI
    if os.environ.get("GEMINI_MODELE"):
        _MODELE_GEMINI = os.environ["GEMINI_MODELE"]
        return _MODELE_GEMINI

    def version(nom):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)-flash$", nom)
        return tuple(int(x) for x in m.group(1).split(".")) if m else None

    noms = []
    for m in client.models.list():
        nom = m.name.split("/")[-1]
        if version(nom) is not None and "generateContent" in (m.supported_actions or []):
            noms.append(nom)
    noms.sort(key=version, reverse=True)
    # Test court (30 s) : un modèle qui ne répond pas à une phrase ne doit pas
    # bloquer la traduction 3 minutes avant qu'on passe au suivant.
    from google import genai
    from google.genai import types
    rapide = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=30_000))
    for nom in noms:
        debut = time.time()
        try:
            _gemini(rapide, nom, "Translate to Spanish, output only the translation: God is love.")
        except Exception as e:
            print(f"      ({nom} indisponible : {str(e)[:80]})")
            continue
        duree = time.time() - debut
        if duree > 45:
            print(f"      ({nom} trop lent : {duree:.0f} s)")
            continue
        print(f"      Modèle Gemini : {nom} ({duree:.0f} s)")
        _MODELE_GEMINI = nom
        return nom
    raise RuntimeError("aucun modèle Gemini flash disponible avec cette clé")


class QuotaEpuise(Exception):
    """Le quota gratuit (journalier) de Gemini est épuisé : inutile d'insister."""


_CLIENT_GEMINI = None


def traduire_gemini(texte: str, source: str, cible_nom: str) -> str:
    """Traduit un morceau avec Gemini. Lève QuotaEpuise si le quota du jour est atteint."""
    global _CLIENT_GEMINI
    from google import genai
    from google.genai import types

    if _CLIENT_GEMINI is None:
        # Délai maximum de 3 minutes par requête : le service bloque parfois.
        _CLIENT_GEMINI = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                                      http_options=types.HttpOptions(timeout=180_000))
    client = _CLIENT_GEMINI
    try:
        modele = modele_gemini(client)
    except Exception as e:
        # Aucun modèle ne répond (quota épuisé, service saturé) : inutile de réessayer à chaque partie.
        raise QuotaEpuise(str(e)[:120]) from e
    bible = BIBLES.get(cible_nom, "the standard Protestant Bible of that language")
    prompt = (
        f"Translate this Christian (Baptist) sermon excerpt from '{source}' into {cible_nom}. "
        f"Keep the warm, spoken tone of a preacher. For Bible books, names, places and quoted "
        f"verses, use the wording of {bible}. Write Bible references as book, chapter and verse "
        f"the way a reader of that language would say them aloud. "
        f"The text will be read aloud by a voice: output plain text only, with no Markdown, "
        f"no asterisks, no bullet points, no headings and no notes. "
        f"Output only the translation, nothing else.\n\n{texte}"
    )
    for essai in range(4):
        try:
            return _gemini(client, modele, prompt).strip()
        except Exception as e:
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg and re.search(r"per ?day|PerDay|daily", msg, re.I):
                raise QuotaEpuise(msg[:120]) from e
            if essai == 3:
                raise
            # Limite par minute : Gemini indique combien de secondes attendre.
            m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)\s*s", msg, re.I)
            attente = min(65, float(m.group(1)) + 2) if m else 15 * (essai + 1)
            print(f"      Gemini occupé ({msg[:80]}), nouvel essai dans {attente:.0f} s…")
            time.sleep(attente)


# Codes de langue du modèle NLLB (traduction locale de secours)
NLLB_CODES = {"zh": "zho_Hans", "es": "spa_Latn", "ru": "rus_Cyrl", "hi": "hin_Deva",
              "en": "eng_Latn", "fr": "fra_Latn", "pt": "por_Latn", "ar": "arb_Arab"}
NLLB_MODELE = "facebook/nllb-200-distilled-600M"
_NLLB = None


def traduire_nllb(texte: str, source: str, cible: str) -> str:
    """Traduction locale avec NLLB (Meta) : gratuite, sans limite, un peu moins bonne."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        # Installé seulement quand on en a besoin (1 à 2 min), pour ne pas ralentir les autres cas.
        import subprocess
        print("      Installation de la traduction locale (PyTorch)…", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "torch",
                        "--index-url", "https://download.pytorch.org/whl/cpu"], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers", "sentencepiece"], check=True)
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    global _NLLB
    if _NLLB is None:
        print(f"      Traduction locale avec {NLLB_MODELE} (téléchargé la première fois)…")
        torch.set_num_threads(os.cpu_count() or 4)
        _NLLB = (AutoTokenizer.from_pretrained(NLLB_MODELE, src_lang=NLLB_CODES[source]),
                 AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODELE).eval())
    tok, model = _NLLB
    cible_id = tok.convert_tokens_to_ids(NLLB_CODES[cible])
    segments = decouper(texte, 400)
    resultat = []
    for i in range(0, len(segments), 8):
        lot = segments[i:i + 8]
        print(f"\r      … {min(i + 8, len(segments))}/{len(segments)}", end="", flush=True)
        entree = tok(lot, return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.no_grad():
            sortie = model.generate(**entree, forced_bos_token_id=cible_id,
                                    max_new_tokens=360, num_beams=2)
        resultat += tok.batch_decode(sortie, skip_special_tokens=True)
    print()
    return " ".join(resultat)


# Bible de référence de chaque langue (pour les noms bibliques et les citations).
BIBLES = {
    "Simplified Chinese": "the Chinese Union Version (和合本)",
    "Spanish": "the Reina-Valera 1960",
    "Russian": "the Russian Synodal Bible (Синодальный перевод)",
    "Hindi": "the Hindi O.V. Bible (पवित्र बाइबिल)",
    "French": "the Louis Segond Bible",
    "English": "the King James Version / ESV",
    "Portuguese": "the Almeida Revista e Corrigida",
    "Arabic": "the Smith & Van Dyke Bible",
}

NOMS_ANGLAIS = {"zh": "Simplified Chinese", "es": "Spanish", "ru": "Russian",
                "hi": "Hindi", "en": "English", "fr": "French",
                "pt": "Portuguese", "ar": "Arabic"}
NOMS_ANGLAIS.update({c: l["nom"] for c, l in TOUTES.items() if c not in NOMS_ANGLAIS})


def traduire(texte: str, source: str, langue: str, moteur: str) -> str:
    """Traduit morceau par morceau : Gemini (si clé), sinon Google, sinon NLLB local.

    Dès qu'un service refuse (quota épuisé, blocage), il est abandonné pour la
    suite au lieu d'être réessayé à chaque morceau : c'est ce qui faisait traîner
    les dernières langues."""
    code_google = LANGUES[langue][0]
    gemini_ok, google_ok = moteur == "gemini", True
    morceaux = decouper(texte, 8000)
    resultat = []
    for i, morceau in enumerate(morceaux, 1):
        print(f"      … partie {i}/{len(morceaux)}", flush=True)
        if gemini_ok:
            try:
                resultat.append(traduire_gemini(morceau, source, NOMS_ANGLAIS[langue]))
                continue
            except QuotaEpuise as e:
                print(f"      Gemini indisponible ({e}). Suite avec Google.")
                gemini_ok = False
            except Exception as e:
                print(f"      Gemini a échoué sur cette partie ({str(e)[:100]}). Google prend le relais.")
        if google_ok:
            try:
                resultat.append(traduire_gtx(morceau, source, code_google))
                continue
            except Exception as e:
                print(f"      Google refuse ({str(e)[:100]}). Suite avec la traduction locale.")
                google_ok = False
        if langue not in NLLB_CODES or source not in NLLB_CODES:
            # Pas de traduction locale pour cette langue : on redonne une chance à Google.
            time.sleep(30)
            resultat.append(traduire_gtx(morceau, source, code_google))
            google_ok = True
            continue
        resultat.append(traduire_nllb(morceau, source, langue))
    return "\n".join(resultat)


# Mots très courants en anglais, absents (ou rares) des autres langues cibles.
MOTS_ANGLAIS = set("""the and that is you we they this was are with have not but what will your our their there
who when because which from of to it he she his her him them be been would could should can do does
did just about into than then if all my me us so very these those has had were""".split()) - {"me", "so", "he"}
# Petits mots très courants en espagnol, français et portugais : leur présence montre que la phrase est traduite.
MOTS_LATINS = set("""el la los las de del que y en un una es por con para se lo su sus al como pero más
le les des et est une du pour dans qui ne pas au aux sur ce cette nous vous il elle
o os da do das dos em não uma""".split())


def phrase_anglaise(phrase: str, langue: str, alphabet_latin: bool = True) -> bool:
    """La phrase est-elle restée en anglais dans une traduction vers `langue` ?"""
    if langue == "en":
        return False
    latines = sum(c.isascii() and c.isalpha() for c in phrase)
    if langue in ("zh", "ru", "hi", "ar") or not alphabet_latin:  # autres alphabets : beaucoup de lettres latines = anglais
        autres = sum(c.isalpha() and not c.isascii() for c in phrase)
        return latines >= 12 and latines > 2 * autres
    mots = re.findall(r"[a-záéíóúñàâçèêëîïôûùüœ']+", phrase.lower())
    if len(mots) < 5:
        return False
    anglais = sum(m in MOTS_ANGLAIS for m in mots)
    latins = sum(m in MOTS_LATINS for m in mots)
    if langue not in ("es", "fr", "pt"):
        # Autres langues à alphabet latin : on ne connaît pas leurs petits mots,
        # on exige donc une phrase nettement anglaise.
        return anglais >= max(3, 0.35 * len(mots))
    return anglais >= 2 and (latins == 0 or anglais >= max(3, 0.3 * len(mots)))


def traduire_phrase(phrase: str, source: str, langue: str) -> str:
    """Retraduit une phrase seule (Google, sinon traduction locale)."""
    try:
        return traduire_gtx(phrase, source, LANGUES[langue][0])
    except Exception as e:
        print(f"      (Google indisponible pour la réparation : {str(e)[:80]})")
        if langue not in NLLB_CODES:
            raise
        return traduire_nllb(phrase, source, langue)


def reparer(traduction: str, source: str, langue: str) -> tuple[str, int]:
    """Retraduit les phrases restées en anglais. Renvoie le texte et le nombre de phrases réparées."""
    if langue == source:
        return traduction, 0
    # Découpe en gardant la ponctuation (le chinois n'a pas d'espace entre les phrases).
    morceaux = re.split(r"(?<=[.!?。！？।])", traduction)
    lettres = [c for c in traduction if c.isalpha()]
    latin = not lettres or sum(c.isascii() for c in lettres) > 0.6 * len(lettres)
    reparees = 0
    for i, m in enumerate(morceaux):
        if not phrase_anglaise(m, langue, latin):
            continue
        debut = m[: len(m) - len(m.lstrip())]
        try:
            nouvelle = traduire_phrase(m.strip(), source, langue).strip()
        except Exception as e:
            print(f"      Phrase non réparée ({str(e)[:80]}) : {m.strip()[:60]}")
            continue
        if nouvelle and not phrase_anglaise(nouvelle, langue, latin):
            morceaux[i] = debut + nouvelle
            reparees += 1
        time.sleep(0.5)
    return "".join(morceaux), reparees


# --------------------------------------------------------------------------
# Nettoyage, corrections de la paroisse et préparation pour la voix
# --------------------------------------------------------------------------
def charger_corrections() -> dict:
    """Lit corrections.json (à côté du programme). Vide si absent ou illisible."""
    import json
    chemin = Path(__file__).with_name("corrections.json")
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        return {}


CORRECTIONS = charger_corrections()


def nettoyer_traduction(texte: str, langue: str) -> str:
    """Retire la mise en forme (Markdown, caractères invisibles) et applique les corrections de traduction."""
    texte = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", texte)
    texte = re.sub(r"\*+|(?<!\w)_{1,2}|_{1,2}(?!\w)|`+|^#+\s*", "", texte, flags=re.M)
    for mauvais, bon in CORRECTIONS.get(langue, {}).get("traduction", {}).items():
        texte = texte.replace(mauvais, bon)
    return texte


# Références bibliques « 3:16 » ou « 3:16-18 », dites en toutes lettres dans chaque langue.
FORMATS_VERSETS = {
    "zh": ("第{c}章{v}节", "第{c}章{v}至{w}节"),
    "es": ("capítulo {c}, versículo {v}", "capítulo {c}, versículos {v} al {w}"),
    "ru": ("глава {c}, стих {v}", "глава {c}, стихи с {v} по {w}"),
    "hi": ("अध्याय {c}, पद {v}", "अध्याय {c}, पद {v} से {w}"),
    "fr": ("chapitre {c}, verset {v}", "chapitre {c}, versets {v} à {w}"),
    "en": ("chapter {c}, verse {v}", "chapter {c}, verses {v} to {w}"),
    "pt": ("capítulo {c}, versículo {v}", "capítulo {c}, versículos {v} a {w}"),
    "ar": ("الأصحاح {c}، الآية {v}", "الأصحاح {c}، الآيات {v} إلى {w}"),
}


def format_versets(langue: str) -> tuple[str, str]:
    """« chapitre 6, verset 14 » dans la langue voulue. Pour les langues sans modèle
    écrit à la main, Google traduit une phrase type et on y remet les nombres."""
    if langue in FORMATS_VERSETS:
        return FORMATS_VERSETS[langue]
    neutre = ("{c}, {v}", "{c}, {v}, {w}")
    try:
        code = LANGUES[langue][0]
        un = traduire_gtx("chapter 6, verse 14", "en", code)
        plage = traduire_gtx("chapter 6, verses 14 to 18", "en", code)
        if all(n in un for n in ("6", "14")) and all(n in plage for n in ("6", "14", "18")):
            un = un.strip(" .。").replace("14", "{v}").replace("6", "{c}")
            plage = plage.strip(" .。").replace("14", "{v}").replace("18", "{w}").replace("6", "{c}")
            FORMATS_VERSETS[langue] = (un, plage)
            print(f"      Références bibliques lues : « {un} »")
            return un, plage
    except Exception as e:
        print(f"      (modèle de verset indisponible : {str(e)[:60]})")
    FORMATS_VERSETS[langue] = neutre
    return neutre


def preparer_pour_voix(texte: str, langue: str) -> str:
    """Texte tel qu'il doit être lu : aucun symbole prononcé, références bibliques en toutes lettres."""
    texte = nettoyer_traduction(texte, langue)
    un, plage = format_versets(langue)

    def verset(m):
        c, v, w = m.group(1), m.group(2), m.group(3)
        if w and int(w) > int(v):
            return plage.format(c=c, v=v, w=w)
        return un.format(c=c, v=v)

    sep = "" if langue == "zh" else " "
    texte = re.sub(r"(?<![\d:])(\d{1,3})\s*[:：]\s*(\d{1,3})(?:\s*[-–—:]\s*(\d{1,3}))?(?![\d:])",
                   lambda m: sep + verset(m) + sep, texte)
    # Symboles que les voix lisent à voix haute
    texte = texte.replace("…", ".").replace("...", ".")
    texte = re.sub(r"[/\\|<>\[\]{}~^=+#@]", " ", texte)
    texte = re.sub(r"\s[-–—]+\s|—|–", ", ", texte)
    texte = re.sub(r"[\"“”«»„‟《》「」『』]", "", texte)
    if langue == "zh":
        texte = re.sub(r"[‘’]", "", texte)
    texte = re.sub(r"[()（）]", ", ", texte)
    if langue == "zh":
        # Ponctuation occidentale au milieu du chinois : la version chinoise est lue comme une pause.
        for a, b in ((",", "，"), (".", "。"), (":", "："), (";", "；"), ("?", "？"), ("!", "！")):
            texte = re.sub(rf"(?<=[\u3400-\u9fff，。]){re.escape(a)}|{re.escape(a)}(?=[\u3400-\u9fff])", b, texte)
        texte = re.sub(r"\s*,\s*", "，", texte)  # virgules ajoutées ci-dessus (tirets, parenthèses)
        texte = texte.replace("．", "。")
        texte = re.sub(r"\s*，\s*(?=[，。！？：；])|(?<=[，。！？：；])\s*，", "", texte)
    for mot, dit in CORRECTIONS.get(langue, {}).get("prononciation", {}).items():
        texte = texte.replace(mot, dit)
    texte = re.sub(r"(,\s*){2,}", ", ", texte)
    texte = re.sub(r"\s+([,.;:?!])", r"\1", texte)  # pas d'espace avant la ponctuation
    texte = re.sub(r",\s*([.?!])", r"\1", texte)
    texte = re.sub(r"[ \t]{2,}", " ", texte)
    return texte


# --------------------------------------------------------------------------
# 3. Synthèse vocale
# --------------------------------------------------------------------------
# Voix de secours si la voix choisie ne répond pas (Microsoft en retire parfois).
VOIX_SECOURS = {
    "zh": ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-YunyangNeural", "zh-CN-XiaoxiaoNeural"],
    "es": ["es-MX-JorgeNeural", "es-ES-AlvaroNeural", "es-US-AlonsoNeural", "es-MX-DaliaNeural"],
    "ru": ["ru-RU-DmitryNeural", "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "ru-RU-SvetlanaNeural"],
    "hi": ["hi-IN-MadhurNeural", "hi-IN-SwaraNeural"],
}


async def voix_candidates(langue: str, preferee: str) -> list[str]:
    """La voix choisie, puis les voix de secours, puis toutes celles de la langue."""
    import edge_tts

    liste = [preferee] + VOIX_SECOURS.get(langue, []) + TOUTES.get(langue, {}).get("voix", [])
    liste = [v for v in liste if v]
    try:
        code = (liste[0].split("-")[0] if liste else LANGUES[langue][0].split("-")[0])
        toutes = await asyncio.wait_for(edge_tts.list_voices(), timeout=60)
        hommes = [v["ShortName"] for v in toutes
                  if v["Locale"].startswith(code + "-") and v.get("Gender") == "Male"]
        autres = [v["ShortName"] for v in toutes if v["Locale"].startswith(code + "-")]
        liste += hommes + autres
    except Exception as e:
        print(f"      (liste des voix indisponible : {e})")
    return list(dict.fromkeys(liste))  # sans doublons, dans l'ordre


async def un_morceau(morceau: str, voix: str, vitesse: str) -> bytes:
    import edge_tts

    async def generer():
        tampon = bytearray()
        async for bloc in edge_tts.Communicate(morceau, voix, rate=vitesse).stream():
            if bloc["type"] == "audio":
                tampon.extend(bloc["data"])
        if not tampon:
            raise RuntimeError("aucun son reçu")
        return bytes(tampon)

    # Le service bloque parfois sans répondre : on coupe au bout de 2 minutes.
    return await asyncio.wait_for(generer(), timeout=120)


async def lire_a_voix_haute(texte: str, langue: str, preferee: str, sortie: Path, vitesse: str):
    """Lit le texte morceau par morceau et concatène les MP3 (même format).

    Le service de voix refuse parfois un morceau au hasard : chaque morceau est
    réessayé plusieurs fois, puis lu par une voix de secours si besoin."""
    voix = await voix_candidates(langue, preferee)
    print(f"[3/3] Voix {voix[0]}…")
    morceaux = decouper(preparer_pour_voix(texte, langue), 1500)
    secours = 0
    # On écrit dans un fichier temporaire, renommé seulement une fois complet :
    # un arrêt en plein milieu ne laisse jamais un MP3 à moitié fait.
    partiel = sortie.with_name(sortie.name + ".partiel")
    with open(partiel, "wb") as f:
        for i, morceau in enumerate(morceaux, 1):
            print(f"\r      … morceau {i}/{len(morceaux)}", end="", flush=True)
            for n, v in enumerate(voix[:4]):
                essais = 3 if n == 0 else 2
                for essai in range(essais):
                    try:
                        f.write(await un_morceau(morceau, v, vitesse))
                        break
                    except Exception as e:
                        print(f"\n      Morceau {i}, voix {v} : {str(e)[:80] or type(e).__name__}"
                              f" (essai {essai + 1}/{essais})")
                        await asyncio.sleep(3 * (essai + 1))
                else:
                    continue  # tous les essais ont échoué : voix suivante
                if n:
                    secours += 1
                break
            else:
                partiel.unlink(missing_ok=True)
                raise RuntimeError(f"aucune voix n'a pu lire le morceau {i}")
    partiel.replace(sortie)
    print()
    if secours:
        print(f"      ({secours} morceau(x) lu(s) par une voix de secours)")


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description="Traduit une prêche MP3 en plusieurs langues.")
    p.add_argument("audio", type=Path, help="Fichier audio de la prêche (MP3, WAV, M4A…)")
    p.add_argument("--langues", nargs="+", default=LANGUES_PAR_DEFAUT,
                   choices=sorted(LANGUES), help="Langues cibles (défaut : zh es ru ; liste complète dans langues.json)")
    p.add_argument("--source", default="en", help="Langue parlée dans la prêche (défaut : en)")
    p.add_argument("--modele", default="small",
                   help="Modèle Whisper : tiny, base, small, medium, large-v3 (défaut : small)")
    p.add_argument("--moteur", choices=["google", "gemini"], default="google",
                   help="Moteur de traduction (gemini demande GEMINI_API_KEY, gratuit)")
    p.add_argument("--vitesse", default="+0%", help="Vitesse de la voix, ex. -10%% ou +5%%")
    p.add_argument("--voix", nargs="*", default=[], metavar="LANGUE=VOIX",
                   help="Changer une voix, ex. es=es-ES-AlvaroNeural")
    p.add_argument("--sortie", type=Path, default=None, help="Dossier de sortie")
    p.add_argument("--transcription-seule", action="store_true",
                   help="Faire seulement la transcription (les langues viendront ensuite)")
    args = p.parse_args()

    if args.moteur == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        print("Le moteur gemini demande la variable GEMINI_API_KEY "
              "(clé gratuite sur https://aistudio.google.com/apikey).")
        return 1

    voix = {k: v for k, v in (x.split("=", 1) for x in args.voix)}
    dossier = args.sortie or Path("sortie") / args.audio.stem
    dossier.mkdir(parents=True, exist_ok=True)

    # 1. Transcription (réutilisée si déjà faite)
    fichier_transcription = dossier / f"{args.audio.stem}.{args.source}.txt"
    if fichier_transcription.exists():
        print(f"[1/3] Transcription déjà faite : {fichier_transcription}")
        texte = fichier_transcription.read_text(encoding="utf-8")
    else:
        if not args.audio.exists():
            print(f"Fichier introuvable : {args.audio}")
            return 1
        texte = transcrire(args.audio, args.modele, args.source)
        fichier_transcription.write_text(texte, encoding="utf-8")
        print(f"      → {fichier_transcription}")
    if args.transcription_seule:
        return 0

    echecs = []
    for langue in args.langues:
        nom = LANGUES[langue][1]
        print(f"\n=== {nom.upper()} ===")
        try:
            # 2. Traduction (réutilisée si déjà faite : on peut corriger le .txt
            #    à la main puis relancer pour régénérer seulement l'audio)
            fichier_trad = dossier / f"{args.audio.stem}.{langue}.txt"
            if fichier_trad.exists():
                print(f"[2/3] Traduction déjà faite : {fichier_trad}")
                traduction = fichier_trad.read_text(encoding="utf-8")
            else:
                print(f"[2/3] Traduction en {nom} ({args.moteur})…")
                traduction = traduire(texte, args.source, langue, args.moteur)
                fichier_trad.write_text(traduction, encoding="utf-8")
                print(f"      → {fichier_trad}")

            # Mise en forme retirée et corrections de la paroisse (corrections.json).
            fichier_mp3 = dossier / f"{args.audio.stem}.{langue}.mp3"
            propre = nettoyer_traduction(traduction, langue)
            if propre != traduction:
                traduction = propre
                fichier_trad.write_text(traduction, encoding="utf-8")
                fichier_mp3.unlink(missing_ok=True)
                print("      Texte nettoyé (mise en forme, corrections).")

            # Vérification : les phrases restées en anglais sont retraduites une par une.
            traduction, n = reparer(traduction, args.source, langue)
            if n:
                fichier_trad.write_text(traduction, encoding="utf-8")
                fichier_mp3.unlink(missing_ok=True)  # l'audio doit suivre le texte corrigé
                print(f"      {n} phrase(s) restée(s) en anglais retraduite(s).")

            # 3. Voix (sautée si le MP3 existe déjà : supprime-le pour le refaire)
            fichier_mp3 = dossier / f"{args.audio.stem}.{langue}.mp3"
            if not voix.get(langue, LANGUES[langue][2]):
                print("[3/3] Aucune voix disponible pour cette langue : texte seulement.")
                continue
            if fichier_mp3.exists() and fichier_mp3.stat().st_size > 0:
                print(f"[3/3] Audio déjà fait : {fichier_mp3}")
                continue
            asyncio.run(lire_a_voix_haute(
                traduction, langue, voix.get(langue, LANGUES[langue][2]),
                fichier_mp3, args.vitesse))
            print(f"      → {fichier_mp3}")
        except Exception as e:
            print(f"\n!!! Échec pour le {nom} : {e}")
            echecs.append(nom)

    print(f"\nFichiers dans : {dossier.resolve()}")
    if echecs:
        print(f"Échec pour : {', '.join(echecs)}. Relance pour réessayer ces langues.")
        return 1
    print("Terminé !")
    return 0


if __name__ == "__main__":
    sys.exit(main())
