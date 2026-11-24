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

## La façon simple : la page `index.html`

Tu déposes ton MP3 dans une page web. GitHub fait tout le travail gratuitement sur ses serveurs, puis tu écoutes ou télécharges les traductions dans la même page. Il n'y a rien à installer.

**Une seule fois :**
1. Sur GitHub, ouvre `index.html` puis clique sur l'icône **Download raw file** (flèche vers le bas). Garde le fichier où tu veux, par exemple sur ton Bureau.
2. Double-clique dessus : la page s'ouvre dans ton navigateur.
3. Elle demande une **clé d'accès GitHub** et explique comment la créer (2 minutes).

**À chaque prêche :** glisse un ou plusieurs MP3 dans la page et clique sur **Traduire**. Les fichiers sont envoyés un par un, puis traduits en parallèle sur GitHub. Compte environ 1 h 30 pour 45 minutes de prêche ; la page affiche le temps restant estimé. Tu peux fermer la page et revenir plus tard.

**Langues :** chinois, espagnol et russe sont cochés par défaut ; hindi, français et anglais en un clic. « Autres langues » ouvre la liste complète des 249 langues de Google Traduction (avec recherche). 79 d'entre elles ont une voix ; pour les autres, tu reçois la traduction écrite seulement. La liste est dans `langues.json`.

**Annuler :** chaque traduction en cours et chaque compression a un bouton **Annuler**. Une traduction annulée n'enregistre rien ; si rien n'avait encore été traduit, le fichier envoyé est aussi supprimé.

Formats acceptés : MP3, MPEG (audio ou vidéo, seule la piste audio est utilisée), M4A, WAV, OGG.

**Compresser des MP3 :** la section « Compresser des MP3 » de la page est indépendante de la traduction. Dépose un ou plusieurs fichiers MP3 ou MPEG, choisis la taille du résultat, puis clique sur **Compresser**. Le workflow `compresser.yml` les convertit avec ffmpeg en MP3 plus léger : 64 kb/s mono par défaut, soit environ 29 Mo par heure. Ça prend 1 à 3 minutes par fichier. Les fichiers compressés apparaissent sous le bouton, prêts à écouter ou télécharger.

**Suppression automatique :** chaque jour, le workflow `nettoyage.yml` supprime les prêches envoyées il y a plus de 30 jours (MP3 reçus et traductions), puis compacte l'historique de la branche pour que GitHub libère vraiment la place. La page indique la date de suppression de chaque prêche. Pour changer la durée, modifie `30` dans `.github/workflows/nettoyage.yml` et `CONSERVATION_JOURS` dans `index.html`.

Les fichiers sont rangés sur la branche `preches` du repo (`entrees/` pour les MP3 reçus, `resultats/` pour les traductions, `compression/` pour les fichiers compressés, supprimés eux aussi après 30 jours). Le plan gratuit de GitHub donne 2000 minutes de calcul par mois sur un repo privé, soit environ 60 à 100 prêches.

Pour une meilleure traduction avec Gemini, ajoute ta clé gratuite comme secret `GEMINI_API_KEY` dans *Settings → Secrets and variables → Actions*. Le workflow l'utilise alors automatiquement.

## La façon manuelle : sur ton ordinateur

### Installation (une seule fois)

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

### Utilisation

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
