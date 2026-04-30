#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════╗
║        MONTAGE IA — Powered by Claude Code       ║
╚══════════════════════════════════════════════════╝

Usage :
  python montage.py

1. Déposez "Plan 1.mp4" et "Plan 2.mp4" dans Projets/Video_XX
2. Lancez cette commande
"""

import os
import sys

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJETS_DIR = os.path.join(BASE_DIR, "Projets")

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".mts", ".m2ts", ".wmv"}

# ── Paramètres de montage ──────────────────────────────────────────────────────
CUT_PLAN1_SEC = 15   # durée Plan 1 par cycle
CUT_PLAN2_SEC = 10   # durée Plan 2 par cycle
# ──────────────────────────────────────────────────────────────────────────────


def find_next_project():
    for i in range(1, 16):
        folder = os.path.join(PROJETS_DIR, f"Video_{i:02d}")
        if not os.path.isdir(folder):
            continue
        videos = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS and not f.startswith(".")
        ])
        if len(videos) == 2:
            return folder, videos
        if len(videos) > 2:
            print(f"⚠️  {os.path.basename(folder)} : {len(videos)} vidéos trouvées (attendu 2). Ignoré.")
    return None, None


def hr(char="─", n=52):
    print(char * n)


def main():
    print()
    hr("═")
    print("   MONTAGE IA — Claude Code")
    hr("═")
    print()

    # Nom du dossier passé en argument : python3 montage.py Video_01
    if len(sys.argv) > 1:
        project_name = sys.argv[1]
        folder = os.path.join(PROJETS_DIR, project_name)
        if not os.path.isdir(folder):
            print(f"❌  Dossier introuvable : {folder}")
            print(f"   Créez-le et déposez Plan 1.mp4 + Plan 2.mp4 dedans.\n")
            sys.exit(1)
        videos = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS and not f.startswith(".")
        ])
        if len(videos) != 2:
            print(f"❌  {folder} doit contenir exactement 2 vidéos ({len(videos)} trouvée(s)).\n")
            sys.exit(1)
    else:
        folder, videos = find_next_project()
        if not folder:
            print("❌  Aucun dossier Projets/Video_XX avec exactement 2 vidéos trouvé.")
            print(f"\n   Usage : python3 montage.py Video_01\n")
            sys.exit(1)
        project_name = os.path.basename(folder)

    # Identifier Plan 1 et Plan 2 par le nom de fichier
    plan1_path = None
    plan2_path = None
    for v in videos:
        name = os.path.basename(v).lower()
        if "plan 1" in name or "plan1" in name:
            plan1_path = v
        elif "plan 2" in name or "plan2" in name:
            plan2_path = v

    if not plan1_path or not plan2_path:
        # Fallback : Plan 1 = meilleur audio
        plan1_path, plan2_path = videos[0], videos[1]
        print("⚠️  Noms 'Plan 1' / 'Plan 2' non détectés — utilisation de l'ordre alphabétique.")

    print(f"✅  Projet : {project_name}")
    print(f"   🎯  Plan 1 (principal) → {os.path.basename(plan1_path)}")
    print(f"   📷  Plan 2 (secondaire) → {os.path.basename(plan2_path)}")
    print()

    # Imports
    try:
        from scripts.audio import find_sync_offset, find_discussion_start, detect_repetitions
        from scripts.premiere import launch_premiere, run_jsx
        from scripts.xml_generator import generate_xml
    except ImportError as e:
        print(f"❌  Module manquant : {e}")
        print("   Lancez d'abord :  bash setup.sh")
        sys.exit(1)

    # 1. Début réel de la discussion
    print("🔍  Détection du début de la discussion (Plan 1) …")
    try:
        disc_start = find_discussion_start(plan1_path)
        m, s = divmod(int(disc_start), 60)
        print(f"   ✅  Discussion commence à {m}:{s:02d} ({disc_start:.1f}s) — début coupé")
    except Exception as e:
        print(f"   ⚠️  Détection échouée ({e}) — début à 0s")
        disc_start = 0.0
    print()

    # 2. Synchronisation Plan 1 → Plan 2
    print("⏱️   Synchronisation audio Plan 1 / Plan 2 …")
    try:
        offset = find_sync_offset(plan1_path, plan2_path)
        print(f"   ✅  Décalage détecté : {offset:+.3f}s")
        print(f"   (Plan 2 source = Plan 1 source − {offset:+.3f}s)")
    except Exception as e:
        print(f"   ⚠️  Sync échouée ({e}) — décalage = 0")
        offset = 0.0
    print()

    # 3. Résumé des coupes
    import av
    c = av.open(plan1_path)
    total_sec = float(c.duration) / av.time_base - disc_start
    c.close()
    cycle = CUT_PLAN1_SEC + CUT_PLAN2_SEC
    n_cycles = int(total_sec / cycle)
    print(f"✂️   Montage multicam :")
    print(f"   Plan 1 : {CUT_PLAN1_SEC}s  →  Plan 2 : {CUT_PLAN2_SEC}s  →  repeat")
    print(f"   {n_cycles} cycles sur {total_sec/60:.1f} min de discussion")
    print()

    # 4. Détection des répétitions
    print("🔴  Détection des répétitions dans Plan 1 …")
    try:
        reps = detect_repetitions(plan1_path, discussion_start=disc_start)
    except Exception as e:
        print(f"   ⚠️  Détection échouée ({e}) — aucun marqueur")
        reps = []
    print()

    # 5. Générer le XML
    print("⚙️   Génération du fichier XML …")
    sequence_name = f"Montage_{project_name}"
    xml_path = os.path.join(folder, "_montage_sequence.xml")
    generate_xml(
        plan1_path=plan1_path,
        plan2_path=plan2_path,
        sync_offset=offset,
        discussion_start=disc_start,
        cut_p1_sec=CUT_PLAN1_SEC,
        cut_p2_sec=CUT_PLAN2_SEC,
        repetitions=reps,
        sequence_name=sequence_name,
        output_path=xml_path,
    )
    print(f"   ✅  Fichier XML : {xml_path}")
    print()

    # 5. Ouvrir Premiere Pro et importer
    print("🚀  Ouverture de Adobe Premiere Pro …")
    launch_premiere()
    print()

    print("▶️   Import dans Premiere Pro …")
    success = run_jsx(xml_path)
    print()

    hr("═")
    if success:
        print("✅  SÉQUENCE IMPORTÉE dans Premiere Pro !")
        print(f"   Séquence : {sequence_name}")
        print()
        print("   Structure :")
        print(f"   V1/A1 → Plan 1 complet (depuis {m}:{s:02d}), audio actif")
        print(f"   V2/A2 → Plan 2 synchronisé, toutes les {cycle}s pendant {CUT_PLAN2_SEC}s, audio muté")
        print(f"   🔴  {len(reps)} marqueurs rouges de répétition sur la timeline")
        print()
        print("   Si le son est décalé : sélectionner V1+V2 → clic droit → Synchroniser → Audio")
    else:
        print("⚠️  Import manuel : Fichier → Importer → sélectionner le XML ci-dessus")
    hr("═")
    print()


if __name__ == "__main__":
    main()
