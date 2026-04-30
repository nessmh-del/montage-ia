"""Pont entre Claude Code et Adobe Premiere Pro via osascript (Mac)."""

import subprocess
import time
import os
import sys

PREMIERE_CANDIDATES = [
    "Adobe Premiere Pro 2026",
    "Adobe Premiere Pro 2025",
    "Adobe Premiere Pro 2024",
    "Adobe Premiere Pro 2023",
    "Adobe Premiere Pro 2022",
    "Adobe Premiere Pro",
]


def _find_premiere_name():
    """Détecte le nom exact de l'application Premiere Pro installée."""
    for name in PREMIERE_CANDIDATES:
        result = subprocess.run(
            ["osascript", "-e", f'tell application "{name}" to return version'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return name
    return "Adobe Premiere Pro 2026"


def _is_premiere_ready(name):
    """Retourne True si Premiere Pro est lancé (via pgrep, sans Accessibilité)."""
    result = subprocess.run(
        ["pgrep", "-f", "Adobe Premiere Pro"],
        capture_output=True, text=True
    )
    return result.returncode == 0


def launch_premiere():
    """Ouvre Premiere Pro et attend qu'il soit prêt (jusqu'à 90s)."""
    name = _find_premiere_name()
    print(f"   Lancement de : {name}")
    subprocess.run(["open", "-a", name], capture_output=True)

    max_wait = 90
    print(f"   ⏳  Attente de Premiere Pro (jusqu'à {max_wait}s) …", end="", flush=True)

    for i in range(max_wait):
        time.sleep(1)
        sys.stdout.write(f"\r   ⏳  {i+1}s / {max_wait}s …   ")
        sys.stdout.flush()
        if _is_premiere_ready(name):
            # Quelques secondes supplémentaires pour que l'UI soit stable
            time.sleep(4)
            print(f"\r   ✅  Premiere Pro prêt ({i+5}s)          ")
            return name

    print(f"\r   ⚠️  Premiere Pro toujours en chargement après {max_wait}s — tentative quand même …")
    return name


def run_jsx(xml_path):
    """
    Importe le fichier XML (FCP7 XMEML) dans Premiere Pro.
    Utilise 'open -a' qui déclenche l'import natif sans permission Accessibilité.
    """
    name = _find_premiere_name()

    # Méthode principale : open -a déclenche l'import XMEML natif de Premiere Pro
    result = subprocess.run(["open", "-a", name, xml_path],
                            capture_output=True, text=True)

    if result.returncode == 0:
        time.sleep(1)
        # Amener Premiere Pro au premier plan
        subprocess.run(["osascript", "-e", f'tell application "{name}" to activate'],
                       capture_output=True)
        return True

    # Fallback : copie dans le presse-papiers + instructions
    print(f"\n   ⚠️  Import automatique impossible (exit {result.returncode}).")
    _copy_to_clipboard(xml_path)
    print(f"\n   👉 Dans Premiere Pro :")
    print(f"      Fichier → Importer (Cmd+I) → Cmd+Shift+G → Cmd+V → Entrée")
    _open_in_finder(xml_path)
    return False


def _copy_to_clipboard(path):
    """Copie le chemin du JSX dans le presse-papiers."""
    subprocess.run(["pbcopy"], input=path.encode(), capture_output=True)
    print(f"   📋  Chemin copié dans le presse-papiers (Cmd+V pour coller)")


def _open_in_finder(path):
    """Ouvre le Finder sur le dossier contenant le fichier JSX."""
    subprocess.run(["open", "-R", path], capture_output=True)
    print(f"   📂  Finder ouvert sur le fichier JSX")


def _request_accessibility(jsx_path):
    """Informe l'utilisateur et ouvre les préférences Accessibilité."""
    print(f"\n   🔒  Permission Accessibilité requise (une seule fois) :")
    print(f"      Les Réglages Système vont s'ouvrir →")
    print(f"      Confidentialité → Accessibilité → cochez 'Terminal' ou 'Code'")
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        capture_output=True
    )
