"""Analyse audio — synchronisation et détection du début de discussion."""

import numpy as np


def _load_audio(video_path, sr=22050, duration=None):
    try:
        import av
        container = av.open(str(video_path))
        if not container.streams.audio:
            raise RuntimeError("Aucune piste audio")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=sr)
        chunks = []
        max_samples = int(duration * sr) if duration else None
        done = False
        for frame in container.decode(container.streams.audio[0]):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray()[0].astype(np.float32))
                if max_samples and sum(len(c) for c in chunks) >= max_samples:
                    done = True
                    break
            if done:
                break
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray()[0].astype(np.float32))
        container.close()
        y = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        if max_samples:
            y = y[:max_samples]
        return y, sr
    except Exception:
        import librosa, warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            y, _ = librosa.load(video_path, sr=sr, mono=True, duration=duration)
        return y, sr


def detect_best_audio(video1_path, video2_path, sample_duration=60):
    """Retourne 0 si video1 a le meilleur audio, 1 sinon."""
    y1, _ = _load_audio(video1_path, duration=sample_duration)
    y2, _ = _load_audio(video2_path, duration=sample_duration)
    rms1 = float(np.sqrt(np.mean(y1 ** 2)))
    rms2 = float(np.sqrt(np.mean(y2 ** 2)))
    print(f"   RMS Plan1={rms1:.5f}  RMS Plan2={rms2:.5f}")
    return 0 if rms1 >= rms2 else 1


def find_sync_offset(plan1_path, plan2_path, sr=22050, max_offset_sec=60):
    """
    Retourne le décalage en secondes entre Plan 1 et Plan 2.
    Plan2_source = Plan1_source - offset
    (offset > 0 → Plan 2 a démarré APRÈS Plan 1)
    """
    y1, _ = _load_audio(plan1_path, sr=sr, duration=300)
    y2, _ = _load_audio(plan2_path, sr=sr, duration=300)

    hop_sec = 0.05
    hop = int(sr * hop_sec)
    win = hop * 2

    def envelope(y):
        e = np.array([np.sqrt(np.mean(y[i:i+win]**2))
                      for i in range(0, len(y)-win, hop)], dtype=np.float32)
        return e / (np.max(e) + 1e-8)

    env1 = envelope(y1)
    env2 = envelope(y2)

    n = len(env1) + len(env2) - 1
    E1 = np.fft.rfft(env1, n=n)
    E2 = np.fft.rfft(env2, n=n)
    corr = np.fft.irfft(E1 * np.conj(E2))

    max_lag = int(max_offset_sec / hop_sec)
    search = np.abs(corr).copy()
    search[max_lag:-max_lag] = 0

    lag = int(np.argmax(search))
    if lag > n // 2:
        lag -= n

    return lag * hop_sec


def _load_whisper_audio(plan1_path, duration=None):
    """Charge l'audio via PyAV en float32 16kHz pour Whisper."""
    import av as _av
    container = _av.open(plan1_path)
    stream = container.streams.audio[0]
    resampler = _av.AudioResampler(format="fltp", layout="mono", rate=16000)
    chunks = []
    max_samples = int(duration * 16000) if duration else None
    total = 0
    for frame in container.decode(stream):
        for out in resampler.resample(frame):
            arr = out.to_ndarray()[0].astype(np.float32)
            chunks.append(arr)
            total += len(arr)
            if max_samples and total >= max_samples:
                break
        else:
            continue
        break
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray()[0].astype(np.float32))
    container.close()
    audio = np.concatenate(chunks)
    if max_samples:
        audio = audio[:max_samples]
    return audio


def find_discussion_start(plan1_path, search_duration=900):
    """
    Détecte le moment exact où le speaker dit la salutation d'ouverture :
      - "As salam Aleykum" / "Salam Aleykum"
      - "Bismillah" / "Bismilah"
      - "Cher frère" / "Cher sœur"
      - "Salat wa salam"
    Utilise Whisper pour la transcription avec timestamps.
    Retourne le timestamp en secondes (0.5s de marge avant).
    """
    import whisper
    import tempfile, subprocess, os

    KEYWORDS = [
        "salam", "aleykum", "alaikum", "aleykoum",
        "bismillah", "bismilah", "bismi",
        "frère", "soeur", "sœur",
        "salat", "rassoul", "rasoul",
    ]

    print("   🎙️  Transcription Whisper (premières 15 min) …")

    audio_array = _load_whisper_audio(plan1_path, duration=search_duration)
    use_path = audio_array
    tmp_wav = None

    try:
        model = whisper.load_model("tiny")
        result = model.transcribe(
            use_path,               # numpy array float32 16kHz
            language=None,
            word_timestamps=True,
            fp16=False,
            verbose=False,
        )

        # Chercher la première occurrence d'un mot-clé
        for segment in result.get("segments", []):
            for word_info in segment.get("words", []):
                word = word_info.get("word", "").lower().strip(" .,!?'\"")
                for kw in KEYWORDS:
                    if kw in word:
                        t = float(word_info["start"])
                        margin = max(0.0, t - 0.5)
                        print(f"   🔑  '{word_info['word'].strip()}' détecté à {t:.1f}s")
                        return margin

        # Fallback : pas trouvé → premier segment de parole
        segs = result.get("segments", [])
        if segs:
            t = float(segs[0]["start"])
            print(f"   ⚠️  Salutation non trouvée — premier mot à {t:.1f}s")
            return max(0.0, t - 0.5)

    finally:
        if tmp_wav and os.path.exists(tmp_wav):
            os.remove(tmp_wav)

    return 0.0


def detect_repetitions(plan1_path, discussion_start=0.0):
    """
    Transcrit tout Plan 1 avec Whisper et détecte les répétitions de 2+ mots consécutifs.
    Retourne une liste de (seq_start, seq_end, phrase) en secondes dans la séquence
    (seq_start = timestamp − discussion_start).
    """
    import whisper, re
    from spellchecker import SpellChecker
    spell_fr = SpellChecker(language='fr')

    # Mots islamiques/arabes courants en contexte français → acceptés
    ACCEPTED = {
        "allah", "islam", "coran", "quran", "muslim", "musulman",
        "hadith", "sunna", "sunnah", "iman", "deen", "din",
        "bismillah", "alhamdulillah", "subhanallah", "inshallah",
        "salam", "aleykum", "aleykoum", "alaikum",
        "rasoul", "rassoul", "nabi", "sahaba",
        "frère", "soeur", "cher",
    }

    def normalize(w):
        return re.sub(r"[^\w]", "", w.lower())

    def is_french_phrase(word_texts):
        """Retourne True si tous les mots significatifs sont du français valide."""
        content_words = [w for w in word_texts if len(w) > 3]
        if not content_words:
            return True
        unknown = spell_fr.unknown(
            [w for w in content_words if w not in ACCEPTED]
        )
        return len(unknown) == 0

    print("   🎙️  Transcription complète Whisper (~2-4 min) …")
    audio = _load_whisper_audio(plan1_path)   # audio complet
    model = whisper.load_model("tiny")
    result = model.transcribe(
        audio,
        language=None,
        word_timestamps=True,
        fp16=False,
        verbose=False,
    )

    # Extraire tous les mots avec timestamps
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            text = normalize(w.get("word", ""))
            if text:
                words.append({
                    "text": text,
                    "start": float(w["start"]),
                    "end":   float(w["end"]),
                })

    print(f"   ✅  {len(words)} mots transcrits")

    # Détecter les répétitions : fenêtres de 2 à 5 mots consécutifs répétés
    MIN_GAP_SEC = 3.0   # au moins 3s entre deux marqueurs pour éviter les doublons
    repetitions = []
    last_marker_time = -MIN_GAP_SEC
    i = 0
    while i < len(words):
        found = False
        for k in range(5, 1, -1):           # essayer de la plus grande fenêtre
            if i + 2 * k > len(words):
                continue
            phrase1 = [words[i + j]["text"] for j in range(k)]
            phrase2 = [words[i + k + j]["text"] for j in range(k)]
            if phrase1 == phrase2:
                rep_start  = words[i + k]["start"]
                rep_end    = words[i + 2 * k - 1]["end"]
                phrase_str = " ".join(phrase1)
                seq_start  = rep_start - discussion_start
                seq_end    = rep_end   - discussion_start

                # Ignorer si la phrase contient des mots non-français (arabe phonétique)
                if not is_french_phrase(phrase1):
                    i += 2 * k
                    found = True
                    break

                if seq_start > 0 and (seq_start - last_marker_time) >= MIN_GAP_SEC:
                    repetitions.append((seq_start, seq_end, phrase_str))
                    last_marker_time = seq_start

                i += 2 * k  # sauter les DEUX occurrences
                found = True
                break
        if not found:
            i += 1

    print(f"   🔴  {len(repetitions)} répétition(s) détectée(s)")
    for s, e, p in repetitions[:5]:
        m, sec = divmod(int(s), 60)
        print(f"        {m}:{sec:02d}  « {p} »")
    if len(repetitions) > 5:
        print(f"        … et {len(repetitions)-5} autres")

    return repetitions
