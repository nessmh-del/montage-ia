# Montage IA — Claude Code

Outil de montage automatique multicam pour Adobe Premiere Pro 2026, propulsé par l'IA.

## Ce que ça fait automatiquement

1. **Détecte le début** de la discussion (salutation islamique : "As Salam Aleykum", "Bismillah"…)
2. **Synchronise** les deux caméras par l'audio
3. **Génère le multicam** : Plan 1 (15s) → Plan 2 (10s) → répété
4. **Supprime l'audio** de Plan 2 (Plan 1 = référence sonore)
5. **Détecte les répétitions** dans le discours et place des **marqueurs rouges** sur la timeline
6. **Importe tout automatiquement** dans Premiere Pro

---

## Installation (une seule fois)

### 1. Prérequis
- macOS
- Adobe Premiere Pro 2026
- Python 3.10+

### 2. Installer les dépendances
```bash
bash setup.sh
```

### 3. Ajouter la commande `montage` au terminal
```bash
echo "alias montage='python3 \"$(pwd)/montage.py\"'" >> ~/.zshrc
source ~/.zshrc
```

---

## Utilisation

### Préparer les vidéos
1. Créer un dossier dans `Projets/` — ex : `Video_01`
2. Y déposer exactement **2 fichiers** :
   - `Plan 1.mp4` → caméra principale (meilleur audio)
   - `Plan 2.mp4` → caméra secondaire

### Lancer le montage
```bash
montage Video_01
```

Le script ouvre Premiere Pro et importe la séquence prête à exporter.

---

## Structure du projet

```
Montage IA - Claude/
├── montage.py          # Script principal
├── setup.sh            # Installation des dépendances
├── scripts/
│   ├── audio.py        # Sync, détection début, répétitions (Whisper)
│   ├── xml_generator.py # Génération FCP7 XML pour Premiere Pro
│   └── premiere.py     # Automatisation Premiere Pro (osascript)
└── Projets/
    └── Video_01/       # Déposer Plan 1.mp4 + Plan 2.mp4 ici
```

---

## Paramètres personnalisables

Dans `montage.py` (lignes du haut) :
```python
CUT_PLAN1_SEC = 15   # Durée Plan 1 par cycle (secondes)
CUT_PLAN2_SEC = 10   # Durée Plan 2 par cycle (secondes)
```

---

## Dépendances Python

- `av` (PyAV) — décodage audio/vidéo
- `librosa` — analyse audio
- `numpy` — traitement signal
- `openai-whisper` — transcription et détection des répétitions
- `pyspellchecker` — filtre français pour les répétitions

---

## Licence

Projet personnel — libre d'utilisation et de modification.
