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
LANGUES_PAR_DEFAUT = ["zh", "es", "ru", "hi"]

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
    for morceau in decouper(texte):
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
    for nom in noms:
        debut = time.time()
        try:
            _gemini(client, nom, "Translate to Spanish, output only the translation: God is love.")
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
    modele = modele_gemini(client)
    prompt = (
        f"Translate this Christian sermon excerpt from '{source}' into "
        f"{cible_nom}. Keep the tone of a preacher, translate Bible "
        f"references using the standard Bible names of that language. "
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


NOMS_ANGLAIS = {"zh": "Simplified Chinese", "es": "Spanish", "ru": "Russian",
                "hi": "Hindi", "en": "English", "fr": "French",
                "pt": "Portuguese", "ar": "Arabic"}


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
                print(f"      Quota Gemini du jour épuisé ({e}). Suite avec Google.")
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
        resultat.append(traduire_nllb(morceau, source, langue))
    return "\n".join(resultat)


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

    liste = [preferee] + VOIX_SECOURS.get(langue, [])
    try:
        code = LANGUES[langue][0].split("-")[0]
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
    morceaux = decouper(texte, 1500)
    secours = 0
    with open(sortie, "wb") as f:
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
                sortie.unlink(missing_ok=True)
                raise RuntimeError(f"aucune voix n'a pu lire le morceau {i}")
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
                   choices=sorted(LANGUES), help="Langues cibles (défaut : zh es ru hi)")
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

            # 3. Voix (sautée si le MP3 existe déjà : supprime-le pour le refaire)
            fichier_mp3 = dossier / f"{args.audio.stem}.{langue}.mp3"
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
