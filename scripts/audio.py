"""Analyse audio — synchronisation et détection du début de discussion."""
from __future__ import annotations

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


from fractions import Fraction
from pathlib import Path


def _estimate_audio_offset(
    reference_path: str,
    candidate_path: str,
    max_offset_seconds: float,
    analysis_sample_rate: int = 16_000,
) -> dict:
    """
    Corrélation de phase normalisée (GCC-PHAT) pour une sync précise.
    offset > 0 → candidate démarre APRÈS reference.
    """
    import numpy as np
    import soundfile as sf
    from scipy import signal

    def load_mono(path):
        data, sr = sf.read(Path(path), always_2d=True, dtype="float32")
        mono = np.mean(data, axis=1, dtype=np.float64)
        mono = mono[np.isfinite(mono)]
        mono -= float(np.mean(mono))
        rms  = float(np.sqrt(np.mean(np.square(mono))))
        peak = float(np.max(np.abs(mono)))
        if rms < 1e-6 or peak < 1e-5:
            raise ValueError(f"Audio trop silencieux : {path}")
        mono /= peak
        return mono.astype(np.float64), sr

    def resample(audio, src_sr):
        if src_sr == analysis_sample_rate:
            return audio
        ratio = Fraction(analysis_sample_rate, src_sr).limit_denominator(1_000)
        return signal.resample_poly(audio, ratio.numerator, ratio.denominator).astype(np.float64)

    ref, ref_sr  = load_mono(reference_path)
    can, can_sr  = load_mono(candidate_path)
    ref = resample(ref, ref_sr)
    can = resample(can, can_sr)

    max_lag  = int(round(max_offset_seconds * analysis_sample_rate))
    n        = int(ref.size + can.size - 1)
    fft_size = int(2 ** np.ceil(np.log2(n)))

    ref_fft = np.fft.rfft(ref, fft_size)
    can_fft = np.fft.rfft(can, fft_size)
    xpow    = ref_fft * np.conj(can_fft)
    xpow   /= np.maximum(np.abs(xpow), 1e-12)          # normalisation de phase

    corr = np.fft.irfft(xpow, fft_size)
    corr = np.concatenate((corr[-(can.size - 1):], corr[:ref.size]))
    lags = np.arange(-(can.size - 1), ref.size)

    mask   = (lags >= -max_lag) & (lags <= max_lag)
    s_lags = lags[mask]
    s_cor  = np.abs(corr[mask])
    best   = int(np.argmax(s_cor))
    best_lag      = int(s_lags[best])
    peak_cor      = float(s_cor[best])

    median = float(np.median(s_cor))
    mad    = float(np.median(np.abs(s_cor - median)))
    robust_std    = max(1.4826 * mad, 1e-12)
    peak_z        = (peak_cor - median) / robust_std

    excl  = max(1, int(round(0.02 * analysis_sample_rate)))
    s2    = s_cor.copy()
    s2[max(0, best - excl): best + excl + 1] = 0.0
    second_peak   = float(np.max(s2)) if s2.size else 0.0
    peak_ratio    = peak_cor / max(second_peak, 1e-12)

    confidence = float(np.clip(
        0.55 * (1.0 - np.exp(-peak_z / 8.0))
        + 0.45 * (1.0 - np.exp(-(peak_ratio - 1.0))),
        0.0, 1.0,
    ))

    return {
        "offset_seconds": float(best_lag / analysis_sample_rate),
        "confidence":     confidence,
        "low_confidence": bool(confidence < 0.35 or peak_z < 6.0),
        "peak_z_score":   peak_z,
    }


def _extract_wav(video_path, max_sec=300):
    """Extrait l'audio d'une vidéo en WAV 16kHz mono (pour soundfile)."""
    import av as _av, wave as _wave, tempfile, os
    tmp = tempfile.mktemp(suffix=".wav")
    container = _av.open(video_path)
    stream    = container.streams.audio[0]
    resampler = _av.AudioResampler(format="s16", layout="mono", rate=16000)
    pcm       = bytearray()
    max_samp  = max_sec * 16000
    for frame in container.decode(stream):
        for out in resampler.resample(frame):
            pcm.extend(out.to_ndarray().flatten().astype(np.int16).tobytes())
            if len(pcm) // 2 >= max_samp:
                break
        else:
            continue
        break
    for out in resampler.resample(None):
        pcm.extend(out.to_ndarray().flatten().astype(np.int16).tobytes())
    container.close()
    with _wave.open(tmp, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2)
        wf.setframerate(16000); wf.writeframes(bytes(pcm))
    return tmp


def find_sync_offset(plan1_path, plan2_path, max_offset_sec=60):
    """
    Retourne l'offset en secondes entre Plan 1 (référence) et Plan 2 (candidat).
    offset > 0 → Plan 2 a démarré APRÈS Plan 1
    Plan 2 source = discussion_start + timeline_sec − offset
    """
    import os, tempfile
    wav1 = _extract_wav(plan1_path)
    wav2 = _extract_wav(plan2_path)
    try:
        result = _estimate_audio_offset(
            reference_path=wav1,
            candidate_path=wav2,
            max_offset_seconds=max_offset_sec,
            analysis_sample_rate=16_000,
        )
    finally:
        os.remove(wav1)
        os.remove(wav2)

    offset     = result["offset_seconds"]
    confidence = result["confidence"]

    if result["low_confidence"]:
        print(f"   ⚠️  Sync peu fiable (confiance {confidence:.0%}, z={result['peak_z_score']:.1f})")
        print(f"       Décalage retenu : {offset:+.3f}s — vérifier dans Premiere Pro")
    else:
        print(f"   (confiance {confidence:.0%})")

    return offset


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
