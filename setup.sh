#!/bin/bash
# ─────────────────────────────────────────────
# MONTAGE IA — Installation des dépendances
# À lancer une seule fois avant la première utilisation
# ─────────────────────────────────────────────

echo ""
echo "════════════════════════════════════"
echo "  MONTAGE IA — Installation"
echo "════════════════════════════════════"
echo ""

# Vérifier Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌  Python 3 non trouvé."
    echo "    Installez-le via : https://www.python.org/downloads/"
    exit 1
fi

echo "✅  Python : $(python3 --version)"
echo ""
echo "📦  Installation des dépendances …"
echo ""

pip3 install --upgrade librosa numpy av

echo ""
echo "════════════════════════════════════"
echo "✅  Installation terminée !"
echo ""
echo "Pour lancer le montage :"
echo "  python3 montage.py"
echo "════════════════════════════════════"
echo ""
