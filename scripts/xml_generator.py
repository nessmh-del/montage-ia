"""Génère un fichier FCP7 XML (XMEML v4) pour Adobe Premiere Pro."""

import os


def _probe(path):
    import av
    c = av.open(path)
    vs = c.streams.video[0]
    fps = float(vs.average_rate)
    dur_frames = int(round(float(c.duration) / av.time_base * fps)) if c.duration else 0
    w, h = vs.width, vs.height
    sr = c.streams.audio[0].sample_rate if c.streams.audio else 48000
    c.close()
    return fps, dur_frames, w, h, sr


def _rate(fps):
    return f"<rate><timebase>{int(fps)}</timebase><ntsc>FALSE</ntsc></rate>"


def _file_def(file_id, name, path, dur_frames, fps, w, h, sr):
    url = "file://localhost" + path
    return f"""<file id="{file_id}">
        <name>{name}</name>
        <pathurl>{url}</pathurl>
        {_rate(fps)}
        <duration>{dur_frames}</duration>
        <media>
          <video>
            <samplecharacteristics>
              {_rate(fps)}
              <width>{w}</width>
              <height>{h}</height>
            </samplecharacteristics>
          </video>
          <audio>
            <samplecharacteristics>
              <depth>16</depth>
              <samplerate>{sr}</samplerate>
            </samplecharacteristics>
            <channelcount>2</channelcount>
          </audio>
        </media>
      </file>"""


def _file_ref(file_id):
    return f'<file id="{file_id}"/>'


def _video_clip(clip_id, name, tl_s, tl_e, src_i, src_o, fps, file_elem):
    dur = tl_e - tl_s
    return f"""    <clipitem id="{clip_id}">
      <name>{name}</name>
      <duration>{dur}</duration>
      {_rate(fps)}
      <start>{tl_s}</start>
      <end>{tl_e}</end>
      <in>{src_i}</in>
      <out>{src_o}</out>
      {file_elem}
      <enabled>TRUE</enabled>
      <compositemode>normal</compositemode>
    </clipitem>"""


def _audio_clip(clip_id, name, tl_s, tl_e, src_i, src_o, fps, file_elem, enabled=True):
    dur = tl_e - tl_s
    en = "TRUE" if enabled else "FALSE"
    return f"""    <clipitem id="{clip_id}">
      <name>{name}</name>
      <duration>{dur}</duration>
      {_rate(fps)}
      <start>{tl_s}</start>
      <end>{tl_e}</end>
      <in>{src_i}</in>
      <out>{src_o}</out>
      {file_elem}
      <enabled>{en}</enabled>
      <channelcount>2</channelcount>
    </clipitem>"""


def _marker(idx, phrase, tl_frame, tl_frame_end):
    """Marqueur rouge de répétition pour la timeline Premiere Pro."""
    return f"""    <marker>
      <name>Répétition</name>
      <comment>{phrase}</comment>
      <in>{tl_frame}</in>
      <out>{tl_frame_end}</out>
      <color>Red</color>
    </marker>"""


def generate_xml(plan1_path, plan2_path, sync_offset,
                 discussion_start, cut_p1_sec, cut_p2_sec,
                 repetitions, sequence_name, output_path):
    """
    Structure :
      V1 / A1 → Plan 1 complet depuis discussion_start (audio actif = référence)
      V2 / A2 → Plan 2 aux intervalles [cut_p1, cut_p1+cut_p2], [2*cut_p1+cut_p2, ...] (A2 muté)

    sync_offset : décalage tel que Plan2_source = Plan1_source - sync_offset
                  (calculé par find_sync_offset(plan1, plan2))
    discussion_start : timestamp (sec) dans Plan 1 où la discussion commence vraiment
    cut_p1_sec  : durée Plan 1 par cycle (ex: 15s)
    cut_p2_sec  : durée Plan 2 par cycle (ex: 10s)
    """
    fps, dur1, w, h, sr1 = _probe(plan1_path)
    _,   dur2, _, _, sr2  = _probe(plan2_path)

    p1_name = os.path.basename(plan1_path)
    p2_name = os.path.basename(plan2_path)

    def fr(sec):
        return int(round(sec * fps))

    # Durée utile de Plan 1 après trim du début
    p1_src_start = fr(discussion_start)
    p1_tl_dur    = dur1 - p1_src_start          # frames dispo dans Plan 1
    total_frames = p1_tl_dur                    # longueur de la séquence

    cycle = fr(cut_p1_sec + cut_p2_sec)         # 25s en frames (15+10)
    p1_dur_f = fr(cut_p1_sec)                   # 15s en frames
    p2_dur_f = fr(cut_p2_sec)                   # 10s en frames

    # ── V1 : Plan 1 COMPLET (depuis discussion_start) ────────────────────────
    v1 = _video_clip(
        "ci-v1-1", p1_name,
        0, total_frames,
        p1_src_start, p1_src_start + total_frames,
        fps, _file_def("file-p1", p1_name, plan1_path, dur1, fps, w, h, sr1)
    )

    # ── A1 : audio Plan 1 (référence, actif) ─────────────────────────────────
    a1 = _audio_clip(
        "ci-a1-1", p1_name,
        0, total_frames,
        p1_src_start, p1_src_start + total_frames,
        fps, _file_ref("file-p1"), enabled=True
    )

    # ── V2 + A2 : Plan 2 aux intervalles impairs du cycle ────────────────────
    # Timeline : [p1_dur_f, p1_dur_f+p2_dur_f], [cycle+p1_dur_f, cycle+p1_dur_f+p2_dur_f], ...
    # Plan 2 source : discussion_start(Plan1) + timeline_pos - sync_offset
    #                 puisque Plan2_source = Plan1_source - sync_offset
    #                 et Plan1_source = discussion_start + timeline_pos

    v2_clips = []
    a2_clips = []
    p2_idx = 0
    tl_pos = p1_dur_f   # première coupe Plan 2 commence après les 15 premières secondes

    while tl_pos + p2_dur_f <= total_frames:
        tl_s = tl_pos
        tl_e = tl_pos + p2_dur_f
        n_f  = p2_dur_f

        # Source Plan 2 correspondante
        p1_src_at_cut = discussion_start + tl_s / fps   # sec dans Plan 1
        p2_src_s = fr(p1_src_at_cut - sync_offset)      # sec dans Plan 2
        p2_src_e = p2_src_s + n_f

        # Vérification que la source Plan 2 est valide
        if p2_src_s >= 0 and p2_src_e <= dur2:
            fe_v = (_file_def("file-p2", p2_name, plan2_path, dur2, fps, w, h, sr2)
                    if p2_idx == 0 else _file_ref("file-p2"))
            fe_a = _file_ref("file-p2")

            v2_clips.append(_video_clip(
                f"ci-v2-{p2_idx+1}", p2_name,
                tl_s, tl_e, p2_src_s, p2_src_e,
                fps, fe_v
            ))
            a2_clips.append(_audio_clip(
                f"ci-a2-{p2_idx+1}", p2_name,
                tl_s, tl_e, p2_src_s, p2_src_e,
                fps, fe_a, enabled=False   # audio Plan 2 muté
            ))
            p2_idx += 1

        tl_pos += cycle  # prochain cycle

    v2_block = "\n".join(v2_clips)
    a2_block = "\n".join(a2_clips)

    # ── Marqueurs de répétition (rouge) ──────────────────────────────────────
    marker_items = []
    for idx, (seq_s, seq_e, phrase) in enumerate(repetitions or []):
        tl_s = fr(seq_s)
        tl_e = fr(seq_e)
        if 0 < tl_s < total_frames:
            safe_phrase = phrase.replace("&", "&amp;").replace("<", "&lt;")
            marker_items.append(_marker(idx, safe_phrase, tl_s, tl_e))
    markers_block = (
        "  <markers>\n" + "\n".join(marker_items) + "\n  </markers>"
        if marker_items else ""
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
<sequence>
  <name>{sequence_name}</name>
  <duration>{total_frames}</duration>
  {_rate(fps)}
  <timecode>
    {_rate(fps)}
    <string>00:00:00:00</string>
    <frame>0</frame>
    <displayformat>NDF</displayformat>
  </timecode>
{markers_block}
  <media>
    <video>
      <format>
        <samplecharacteristics>
          {_rate(fps)}
          <width>{w}</width>
          <height>{h}</height>
        </samplecharacteristics>
      </format>
      <track>
{v1}
      </track>
      <track>
{v2_block}
      </track>
    </video>
    <audio>
      <track>
{a1}
      </track>
      <track>
{a2_block}
      </track>
    </audio>
  </media>
</sequence>
</xmeml>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml)

    return output_path
