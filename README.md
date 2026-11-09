# Traduction de prêches

Ce projet prend une prêche en audio (MP3) et produit un MP3 par langue, lu par une voix, en **chinois, espagnol, russe et hindi**.

**100 % gratuit** : pas de clé API ni de carte bancaire, et pas besoin de GPU.

```
preche.mp3 (anglais)
   │ 1. Transcription : faster-whisper (sur ton ordi)
   ▼
texte anglais
   │ 2. Traduction : Google Traduction (gratuit) ou Gemini (clé gratuite)
   ▼
textes zh / es / ru / hi
   │ 3. Voix : edge-tts (voix neuronales Microsoft, gratuit)
   ▼
preche.zh.mp3  preche.es.mp3  preche.ru.mp3  preche.hi.mp3
```

## Installation (une seule fois)

1. Installe [Python 3.10 ou plus récent](https://www.python.org/downloads/). Sous Windows, coche « Add Python to PATH ».
2. Dans un terminal, depuis le dossier du projet :

```bash
python -m venv .venv
# Windows :
.venv\Scripts\activate
# Mac / Linux :
source .venv/bin/activate

pip install -r requirements.txt
```

## Utilisation

```bash
python traduire_preche.py ma_preche.mp3
```

Les fichiers arrivent dans `sortie/ma_preche/` :

| Fichier | Contenu |
|---|---|
| `ma_preche.en.txt` | Transcription anglaise |
| `ma_preche.zh.txt`, `.es.txt`, `.ru.txt`, `.hi.txt` | Traductions écrites |
| `ma_preche.zh.mp3`, `.es.mp3`, `.ru.mp3`, `.hi.mp3` | Traductions audio |

### Options utiles

```bash
# Meilleure transcription (plus lente) : tiny < base < small < medium < large-v3
python traduire_preche.py preche.mp3 --modele medium

# Seulement certaines langues
python traduire_preche.py preche.mp3 --langues es hi

# Prêche en français au lieu de l'anglais, traduite aussi en anglais
python traduire_preche.py preche.mp3 --source fr --langues en es zh ru hi

# Voix un peu plus lente
python traduire_preche.py preche.mp3 --vitesse -10%

# Changer une voix (liste complète : edge-tts --list-voices)
python traduire_preche.py preche.mp3 --voix es=es-ES-AlvaroNeural zh=zh-CN-XiaoxiaoNeural
```

### Corriger une traduction à la main

Les `.txt` déjà présents sont réutilisés. Pour corriger une erreur :

1. Ouvre `sortie/ma_preche/ma_preche.es.txt` et corrige le texte.
2. Supprime `ma_preche.es.mp3`.
3. Relance la même commande : seul l'audio est régénéré.

Pour tout refaire, supprime le dossier `sortie/ma_preche/`.

### Meilleure traduction avec Gemini (gratuit)

Google Traduction est correct. Gemini comprend mieux le contexte : ton de prêche, noms bibliques, expressions.

1. Crée une clé gratuite sur https://aistudio.google.com/apikey.
2. Lance :

```bash
pip install google-genai
# Windows : set GEMINI_API_KEY=ta_cle     Mac/Linux : export GEMINI_API_KEY=ta_cle
python traduire_preche.py preche.mp3 --moteur gemini
```

## Voix par défaut

| Langue | Voix |
|---|---|
| Chinois | `zh-CN-YunxiNeural` (homme) |
| Espagnol | `es-MX-JorgeNeural` (homme) |
| Russe | `ru-RU-DmitryNeural` (homme) |
| Hindi | `hi-IN-MadhurNeural` (homme) |

## Durée de traitement

Pour une prêche de 45 minutes sur un ordinateur portable ordinaire, avec le modèle `small` :

- Transcription : 10 à 20 minutes
- Traduction : moins d'une minute par langue
- Voix : 1 à 3 minutes par langue

Il faut une connexion internet pour la traduction et la voix.

## Limites

- La voix n'est pas celle du prédicateur : c'est une voix de synthèse.
- edge-tts et Google Traduction gratuit sont des services non officiels. Ils peuvent changer ou limiter le nombre de requêtes.
- La traduction automatique fait des erreurs. Relis les `.txt` avant une diffusion publique, surtout les citations bibliques.
