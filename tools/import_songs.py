#!/usr/bin/env python3
"""Turns Guitar Pro and MusicXML files in import/ into Guitar Learn song files.

    python3 tools/import_songs.py              # import every file in import/
    python3 tools/import_songs.py import/x.gp5 # import only these files

For each file it writes <id>.json next to index.json, adds or updates the
song's entry in index.json and raises its version when the notes changed, so
the app downloads the new version. Supported inputs:

  .gp3 .gp4 .gp5          Guitar Pro 3-5 (read with PyGuitarPro)
  .musicxml .xml .mxl     MusicXML, e.g. exported from MuseScore or Guitar Pro

An optional sidecar file import/<same name>.json sets anything the score file
does not know, for example:

  {"id": "moja-pesma", "title": {"en": "My Song", "sr": "Moja pesma"},
   "artist": "Traditional", "difficulty": "easy", "tags": ["serbian-folk"],
   "source": "Traditional Serbian", "track": 1, "tempo": 90}

The "full" track is the guitar part note by note. The "easy" track is one
chord strum per beat; chord names come from the score when it has them,
otherwise they are worked out from the notes in each bar.
"""

import itertools
import json
import os
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_DIR = os.path.join(ROOT, "import")
SCORE_EXTS = (".gp3", ".gp4", ".gp5", ".musicxml", ".xml", ".mxl")
MAX_FRET = 12  # the app's neck shows frets 0-12

NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
STANDARD = [64, 59, 55, 50, 45, 40]  # string 1 (thin) .. string 6
# Chords the importer may pick when it has to guess them from the notes.
DETECT_CHORDS = ["C", "D", "Dm", "E", "Em", "F", "G", "A", "Am", "Bm",
                 "B7", "C7", "D7", "E7", "G7", "A7"]


class ImportError_(Exception):
    """A problem with one input file; the message is shown to the user."""


@dataclass
class Note:
    t: float            # start, in quarter notes from the start of the song
    dur: float          # length, in quarter notes
    midi: int           # pitch without capo
    string: int = None  # 1 (thin) .. 6, when the score says
    fret: int = None
    finger: int = None  # 0-4, when the score says


@dataclass
class Measure:
    start: float        # quarter notes
    length: float
    num: int
    den: int
    notes: list = field(default_factory=list)
    chords: list = field(default_factory=list)  # (t, name)
    repeat_open: bool = False
    repeat_times: int = 0   # total plays when the bar ends a repeat, else 0
    endings: set = field(default_factory=set)


@dataclass
class Score:
    title: str = ""
    artist: str = ""
    tempo: float = 0     # quarter notes per minute
    tuning: list = None  # MIDI, string 1..6
    capo: int = 0
    measures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------- Guitar Pro

def read_guitar_pro(path, track_no):
    try:
        import guitarpro
    except ImportError:
        raise ImportError_("PyGuitarPro is not installed (pip install pyguitarpro)")
    try:
        song = guitarpro.parse(path)
    except Exception as e:
        raise ImportError_(f"could not read the Guitar Pro file: {e}")

    tracks = [t for t in song.tracks if not t.isPercussionTrack]
    if track_no:
        if not 1 <= track_no <= len(song.tracks):
            raise ImportError_(f"track {track_no} does not exist, the file has {len(song.tracks)}")
        track = song.tracks[track_no - 1]
    else:
        six = [t for t in tracks if len(t.strings) == 6 and not re.search(r"voice|vocal|voc|bass|drum|perc", t.name, re.I)]
        six = six or [t for t in tracks if len(t.strings) == 6]
        if not six:
            raise ImportError_("no 6-string guitar track found")
        # Songs often have a short intro track first; take the guitar that plays the most.
        track = max(six, key=_gp_note_count)
    if len(track.strings) != 6:
        raise ImportError_(f"track '{track.name}' has {len(track.strings)} strings, the app needs 6")

    score = Score(title=song.title or "", artist=song.artist or "", tempo=song.tempo or 0,
                  capo=track.offset or 0)
    if len(song.tracks) > 1:
        names = ", ".join(f"{i + 1} {t.name.strip()}" for i, t in enumerate(song.tracks))
        score.warnings.append(f"used track {song.tracks.index(track) + 1} ({track.name.strip()}) of: {names}; "
                              "set \"track\" in the .json file to pick another")
    strings = sorted(track.strings, key=lambda s: s.number)
    score.tuning = [s.value for s in strings]

    origin = track.measures[0].header.start if track.measures else 0
    q = 960.0  # ticks per quarter note
    for m in track.measures:
        h = m.header
        ts = h.timeSignature
        meas = Measure(start=(h.start - origin) / q, length=h.length / q,
                       num=ts.numerator, den=ts.denominator.value,
                       repeat_open=h.isRepeatOpen,
                       repeat_times=h.repeatClose + 1 if h.repeatClose > 0 else 0,
                       endings={i + 1 for i in range(8) if h.repeatAlternative & (1 << i)})
        for voice in m.voices:
            for beat in voice.beats:
                t = (beat.start - origin) / q
                dur = beat.duration.time / q
                chord = getattr(beat.effect, "chord", None)
                if chord is not None and chord.name:
                    meas.chords.append((t, chord.name))
                for n in beat.notes:
                    kind = n.type.name
                    if kind in ("rest", "dead"):
                        continue
                    finger = None
                    lhf = getattr(n.effect, "leftHandFinger", None)
                    if lhf is not None and lhf.value >= -1:
                        finger = max(0, lhf.value) if lhf.value <= 4 else None
                    note = Note(t=t, dur=dur, midi=n.realValue, string=n.string,
                                fret=n.value, finger=finger)
                    if kind == "tie":
                        note.tie = True
                    meas.notes.append(note)
        score.measures.append(meas)
    return score


def _gp_note_count(track):
    return sum(len(b.notes) for m in track.measures for v in m.voices for b in v.beats)


# ------------------------------------------------------------------ MusicXML

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _strip_ns(root):
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _load_xml(path):
    try:
        if path.lower().endswith(".mxl"):
            with zipfile.ZipFile(path) as z:
                name = None
                if "META-INF/container.xml" in z.namelist():
                    c = _strip_ns(ET.fromstring(z.read("META-INF/container.xml")))
                    rf = c.find(".//rootfile")
                    if rf is not None:
                        name = rf.get("full-path")
                if not name:
                    name = next(n for n in z.namelist()
                                if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
                return _strip_ns(ET.fromstring(z.read(name)))
        return _strip_ns(ET.parse(path).getroot())
    except Exception as e:
        raise ImportError_(f"could not read the MusicXML file: {e}")


def _num(el, default=0.0):
    try:
        return float(el.text.strip())
    except (AttributeError, ValueError):
        return default


def _pitch(p):
    step = p.findtext("step").strip()
    alter = round(_num(p.find("alter"), 0))
    octave = int(p.findtext("octave").strip())
    return (octave + 1) * 12 + NOTE_INDEX[step] + alter


def _is_tab_staff(attrs, staff_no):
    for clef in attrs.findall("clef"):
        if clef.get("number", "1") == str(staff_no) and clef.findtext("sign", "").strip() == "TAB":
            return True
    return False


def read_musicxml(path, track_no):
    root = _load_xml(path)
    if root.tag == "score-timewise":
        raise ImportError_("score-timewise MusicXML is not supported; export as normal (partwise) MusicXML")
    if root.tag != "score-partwise":
        raise ImportError_("this is not a MusicXML score")
    parts = root.findall("part")
    if not parts:
        raise ImportError_("the score has no parts")
    names = {sp.get("id"): (sp.findtext("part-name") or "") for sp in root.iter("score-part")}

    def has_tab(part):
        return any(c.findtext("sign", "").strip() == "TAB" for c in part.iter("clef")) or \
            any(sd.findtext("staff-lines", "").strip() == "6" for sd in part.iter("staff-details"))

    if track_no:
        if not 1 <= track_no <= len(parts):
            raise ImportError_(f"track {track_no} does not exist, the file has {len(parts)} parts")
        part = parts[track_no - 1]
    else:
        tabbed = [p for p in parts if has_tab(p)]
        guitar = [p for p in parts if re.search(r"guit|gitar|гитар", names.get(p.get("id"), ""), re.I)]
        part = (tabbed or guitar or parts)[0]

    score = Score()
    score.title = (root.findtext("work/work-title") or root.findtext("movement-title") or "").strip()
    for cr in root.findall("identification/creator"):
        if cr.get("type") in ("composer", "lyricist", "arranger", None) and cr.text and not score.artist:
            score.artist = cr.text.strip()

    divisions = 1.0
    num, den = 4, 4
    tab_staff = None     # the staff number holding the tab, if any
    transpose = 0        # semitones from written to sounding pitch
    has_transpose = False
    tuning = {}
    t0 = 0.0
    last_by_voice = {}   # voice -> start of the last note (for <chord/>)
    open_ties = {}       # midi -> Note waiting for a tie stop

    for m_el in part.findall("measure"):
        meas = Measure(start=t0, length=0, num=num, den=den)
        cursor = 0.0
        longest = 0.0
        for el in m_el:
            tag = el.tag
            if tag == "attributes":
                if el.find("divisions") is not None:
                    divisions = _num(el.find("divisions"), 1) or 1
                time = el.find("time")
                if time is not None and time.find("beats") is not None:
                    try:
                        num = int(time.findtext("beats").split("+")[0])
                        den = int(time.findtext("beat-type"))
                        meas.num, meas.den = num, den
                    except ValueError:
                        pass
                staves = int(el.findtext("staves", "0") or 0)
                for s in range(1, max(staves, 1) + 1):
                    if _is_tab_staff(el, s):
                        tab_staff = s
                tr = el.find("transpose")
                if tr is not None:
                    has_transpose = True
                    transpose = round(_num(tr.find("chromatic"))) + 12 * round(_num(tr.find("octave-change")))
                for sd in el.findall("staff-details"):
                    for st in sd.findall("staff-tuning"):
                        line = int(st.get("line"))
                        step = st.findtext("tuning-step").strip()
                        alter = round(_num(st.find("tuning-alter"), 0))
                        octave = int(st.findtext("tuning-octave").strip())
                        tuning[line] = (octave + 1) * 12 + NOTE_INDEX[step] + alter
                    if sd.find("capo") is not None:
                        score.capo = int(_num(sd.find("capo")))
            elif tag == "backup":
                cursor -= _num(el.find("duration")) / divisions
            elif tag == "forward":
                cursor += _num(el.find("duration")) / divisions
                longest = max(longest, cursor)
            elif tag == "direction" or tag == "sound":
                snd = el if tag == "sound" else el.find("sound")
                if snd is not None and snd.get("tempo") and not score.tempo:
                    score.tempo = float(snd.get("tempo"))
                if not score.tempo and tag == "direction":
                    met = el.find(".//metronome")
                    if met is not None and met.find("per-minute") is not None:
                        unit = {"half": 2, "quarter": 1, "eighth": 0.5}.get(met.findtext("beat-unit", "quarter"), 1)
                        if met.find("beat-unit-dot") is not None:
                            unit *= 1.5
                        score.tempo = _num(met.find("per-minute")) * unit
            elif tag == "harmony":
                name = _harmony_name(el)
                off = _num(el.find("offset")) / divisions if el.find("offset") is not None else 0
                if name:
                    meas.chords.append((t0 + cursor + off, name))
            elif tag == "barline":
                rep = el.find("repeat")
                if rep is not None:
                    if rep.get("direction") == "forward":
                        meas.repeat_open = True
                    elif rep.get("direction") == "backward":
                        meas.repeat_times = int(rep.get("times", "2"))
                end = el.find("ending")
                if end is not None and end.get("type") == "start":
                    meas.endings = {int(x) for x in re.findall(r"\d+", end.get("number", ""))}
            elif tag == "note":
                if el.find("grace") is not None or el.find("cue") is not None:
                    continue
                dur = _num(el.find("duration")) / divisions
                voice = el.findtext("voice", "1").strip()
                if el.find("chord") is not None:
                    start = last_by_voice.get(voice, cursor)
                else:
                    start = cursor
                    cursor += dur
                    longest = max(longest, cursor)
                    last_by_voice[voice] = start
                staff = int(el.findtext("staff", "1") or 1)
                if el.find("rest") is not None or el.find("pitch") is None:
                    continue
                if tab_staff is not None and staff != tab_staff:
                    continue  # the same notes are in the tab staff, with their strings
                if tab_staff is None and staff != 1:
                    continue
                midi = _pitch(el.find("pitch"))
                tech = el.find("notations/technical")
                string = fret = finger = None
                if tech is not None:
                    if tech.find("string") is not None and tech.find("fret") is not None:
                        string = int(_num(tech.find("string")))
                        fret = int(_num(tech.find("fret")))
                    fg = tech.findtext("fingering")
                    if fg and fg.strip().isdigit() and int(fg) <= 4:
                        finger = int(fg)
                ties = {t.get("type") for t in el.findall("tie")}
                note = Note(t=t0 + start, dur=dur, midi=midi, string=string, fret=fret, finger=finger)
                note.written = string is None
                if "stop" in ties and midi in open_ties:
                    prev = open_ties.pop(midi)
                    prev.dur = note.t + dur - prev.t
                    if "start" in ties:
                        open_ties[midi] = prev
                    continue
                if "start" in ties:
                    open_ties[midi] = note
                meas.notes.append(note)
        # A bar is as long as its time signature, except a pickup bar or one
        # that is really shorter (marked implicit).
        full_len = num * 4.0 / den
        meas.length = longest if (m_el.get("implicit") == "yes" or longest < full_len - 1e-6) and longest > 0 \
            else full_len
        if longest > full_len + 1e-6:
            meas.length = longest
        score.measures.append(meas)
        t0 += meas.length

    if len(tuning) == 6:
        score.tuning = [tuning[7 - s] for s in range(1, 7)]  # line 1 is the lowest string
    else:
        score.tuning = list(STANDARD)

    written = [n for m in score.measures for n in m.notes if getattr(n, "written", False)]
    if written:
        # Standard notation for guitar is written an octave above how it sounds.
        if has_transpose:
            shift = transpose
        else:
            shift = -12 if min(n.midi for n in written) >= score.tuning[5] + 12 else 0
        for n in written:
            n.midi += shift
    for m in score.measures:
        for n in m.notes:
            if n.string is not None:
                n.midi = score.tuning[n.string - 1] + n.fret
    return score


KIND_SUFFIX = {
    "major": "", "minor": "m", "dominant": "7", "major-seventh": "maj7",
    "minor-seventh": "m7", "suspended-fourth": "sus4", "suspended-second": "sus2",
    "major-sixth": "6", "minor-sixth": "m6", "dominant-ninth": "9", "minor-ninth": "m9",
    "diminished": "dim", "augmented": "aug", "half-diminished": "m7b5",
    "diminished-seventh": "dim7", "power": "5",
}


def _harmony_name(h):
    root = h.find("root")
    if root is None:
        return None
    step = root.findtext("root-step", "").strip()
    alter = round(_num(root.find("root-alter"), 0))
    kind_el = h.find("kind")
    kind = kind_el.text.strip() if kind_el is not None and kind_el.text else "major"
    suffix = KIND_SUFFIX.get(kind)
    if suffix is None:
        suffix = kind_el.get("text", "") if kind_el is not None else ""
    return step + ("#" if alter > 0 else "b" if alter < 0 else "") + suffix


# ------------------------------------------------------------ Shared steps

def expand_repeats(measures, warnings):
    """Plays repeat signs and 1st/2nd endings out in order."""
    if not any(m.repeat_open or m.repeat_times or m.endings for m in measures):
        return measures
    order = []
    i, start, pass_ = 0, 0, 1
    while i < len(measures) and len(order) < 5000:
        m = measures[i]
        if m.repeat_open and i != start:
            start, pass_ = i, 1
        if m.endings and pass_ not in m.endings:
            i += 1
            continue
        order.append(i)
        if m.repeat_times and pass_ < m.repeat_times:
            pass_ += 1
            i = start
            continue
        if m.repeat_times or (m.endings and (i + 1 == len(measures) or not measures[i + 1].endings)):
            start, pass_ = i + 1, 1
        i += 1
    out = []
    t = 0.0
    for idx in order:
        m = measures[idx]
        shift = t - m.start
        copy = Measure(start=t, length=m.length, num=m.num, den=m.den,
                       notes=[Note(t=n.t + shift, dur=n.dur, midi=n.midi, string=n.string,
                                   fret=n.fret, finger=n.finger) for n in m.notes],
                       chords=[(ct + shift, c) for ct, c in m.chords])
        for old, new in zip(m.notes, copy.notes):
            if getattr(old, "tie", False):
                new.tie = True
        out.append(copy)
        t += m.length
    if len(out) != len(measures):
        warnings.append(f"repeats played out: {len(measures)} bars became {len(out)}")
    return out


def beat_unit(num, den):
    """(length of one app beat in quarter notes, beats per bar)."""
    if den == 8 and num % 3 == 0 and num > 3:
        return 1.5, num // 3  # 6/8, 9/8, 12/8 are counted in dotted quarters
    return 4.0 / den, num


def join_ties(notes):
    """Guitar Pro marks a held note as a 'tie' note in the next beat."""
    out = []
    last_on = {}
    for n in sorted(notes, key=lambda n: n.t):
        if getattr(n, "tie", False):
            prev = last_on.get(n.string)
            if prev is not None:
                prev.dur = max(prev.dur, n.t + n.dur - prev.t)
            continue
        out.append(n)
        if n.string is not None:
            last_on[n.string] = n
    return out


def assign_positions(notes, tuning, warnings):
    """Chooses a string and fret for notes the score gave only as pitches,
    and moves notes above fret 12 to a lower spot on the neck."""
    by_time = {}
    for n in notes:
        by_time.setdefault(round(n.t, 4), []).append(n)
    pos = 1  # the fret the index finger is at
    dropped = 0
    kept = []
    for t in sorted(by_time):
        group = by_time[t]
        fixed = [n for n in group if n.string is not None and n.fret <= MAX_FRET]
        free = [n for n in group if n not in fixed]
        used = {n.string for n in fixed}
        # Several notes on one string at once cannot be played; keep the first.
        dedup = []
        for n in fixed:
            if n.string in {d.string for d in dedup}:
                free.append(n)
            else:
                dedup.append(n)
        fixed = dedup
        used = {n.string for n in fixed}
        options = []
        for n in free:
            opts = []
            for s in range(1, 7):
                fret = n.midi - tuning[s - 1]
                if 0 <= fret <= MAX_FRET and s not in used:
                    opts.append((s, fret))
            options.append(opts)
        best = None
        if free and all(options):
            ranked = [sorted(o, key=lambda sf: _pos_cost(sf, pos))[:4] for o in options]
            for combo in itertools.product(*ranked):
                strings = [s for s, _ in combo]
                if len(set(strings)) != len(strings):
                    continue
                cost = sum(_pos_cost(sf, pos) for sf in combo)
                frets = [f for _, f in combo if f > 0] + [n.fret for n in fixed if n.fret > 0]
                if frets and max(frets) - min(frets) > 4:
                    cost += 20
                if best is None or cost < best[0]:
                    best = (cost, combo)
        if best:
            for n, (s, f) in zip(free, best[1]):
                n.string, n.fret = s, f
            kept.extend(fixed + free)
        else:
            # Place what fits, highest notes first, and drop the rest.
            for n in sorted(free, key=lambda n: -n.midi):
                opts = [(s, n.midi - tuning[s - 1]) for s in range(1, 7)
                        if s not in used and 0 <= n.midi - tuning[s - 1] <= MAX_FRET]
                if opts:
                    s, f = min(opts, key=lambda sf: _pos_cost(sf, pos))
                    n.string, n.fret = s, f
                    used.add(s)
                    fixed.append(n)
                else:
                    dropped += 1
            kept.extend(fixed)
        fretted = [n.fret for n in group if n.fret and n.string is not None]
        if fretted:
            hi, lo = max(fretted), min(fretted)
            if hi > pos + 3:
                pos = max(1, hi - 3)
            elif lo < pos:
                pos = lo
    if dropped:
        warnings.append(f"{dropped} note(s) could not be placed within frets 0-{MAX_FRET} and were left out")
    return sorted(kept, key=lambda n: (n.t, n.string))


def _pos_cost(sf, pos):
    s, fret = sf
    if fret == 0:
        return 0.5
    outside = max(0, fret - (pos + 3)) + max(0, pos - fret)
    return outside * 3 + fret * 0.3


def assign_fingers(notes):
    """Fills in fingers the score did not give: one finger per fret, with the
    index finger on the lowest fret played around that moment."""
    for n in notes:
        if n.finger is not None and not (n.fret > 0 and n.finger == 0):
            continue
        if n.fret == 0:
            n.finger = 0
            continue
        near = [m.fret for m in notes if m.fret > 0 and abs(m.t - n.t) <= 2]
        lo = min(near)
        if n.fret - lo > 3:
            lo = n.fret - 3
        n.finger = max(1, min(4, n.fret - lo + 1))
    for n in notes:
        if n.fret == 0:
            n.finger = 0


# ---------------------------------------------------------------- Chords

def load_chords():
    with open(os.path.join(ROOT, "chords.json"), encoding="utf-8") as f:
        return json.load(f)["chords"]


def chord_root(name):
    m = re.match(r"([A-G])([#b]?)", name)
    pc = NOTE_INDEX[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    return pc % 12


def chord_pcs(shape):
    """Pitch classes a library shape sounds (shapes list string 6 first)."""
    pcs = set()
    for i, fret in enumerate(shape["frets"]):
        if fret >= 0:
            pcs.add((STANDARD[5 - i] + fret) % 12)
    return pcs


def normalize_chord(name, library):
    """Maps a chord name from the score to a shape the app has, or None."""
    name = name.strip().replace("♯", "#").replace("♭", "b").replace("Δ", "maj7")
    if name in library:
        return name
    m = re.match(r"^([A-G][#b]?)(.*?)(?:/[A-G][#b]?)?$", name)
    if not m:
        return None
    root, q = m.group(1), m.group(2)
    enh = {"Db": "C#", "D#": "Eb", "Gb": "F#", "G#": "Ab", "A#": "Bb", "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}
    roots = [root] + ([enh[root]] if root in enh else [])
    q = q.replace("min", "m").replace("-", "m") if not q.startswith("maj") else q
    if q.startswith("M") and not q.startswith("M7"):
        q = q[1:]
    q = {"M7": "maj7", "ma7": "maj7"}.get(q, q)
    tries = [q]
    minor = q.startswith("m") and not q.startswith("maj")
    if q in ("sus", "sus4", "7sus4"):
        tries.append("sus4")
    if minor:
        tries += ["m7"] if "7" in q or "9" in q or "11" in q else []
        tries.append("m")
    else:
        if q.startswith("maj"):
            tries.append("maj7")
        elif re.match(r"^(7|9|11|13)", q):
            tries.append("7")
        tries.append("")
    for r in roots:
        for t in tries:
            if r + t in library:
                return r + t
    return None


def score_chord(pcs, root, notes, start, end):
    length = end - start
    s = 0.0
    lowest = None
    present = set()
    for n in notes:
        ov = min(end, n.t + n.dur) - max(start, n.t)
        if ov <= 0:
            continue
        pc = n.midi % 12
        s += ov if pc in pcs else -ov
        if pc in pcs:
            present.add(pc)
        if lowest is None or n.midi < lowest.midi:
            lowest = n
    if lowest is None:
        return None
    if lowest.midi % 12 == root:
        s += 0.3 * length
    s -= 0.15 * length * len(pcs - present)
    return s


def detect(notes, start, end, candidates, prev=None):
    best = None
    for name, (pcs, root, bonus) in candidates.items():
        sc = score_chord(pcs, root, notes, start, end)
        if sc is None:
            continue
        sc += bonus * (end - start)
        if name == prev:
            sc += 0.1 * (end - start)
        if best is None or sc > best[0]:
            best = (sc, name)
    return best


# Krumhansl-Kessler key profiles, starting from the tonic.
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def find_key(notes):
    """(tonic pitch class, is_minor) that best fits how long each note sounds."""
    hist = [0.0] * 12
    for n in notes:
        hist[n.midi % 12] += n.dur
    if notes:
        last = max(notes, key=lambda n: n.t)
        hist[last.midi % 12] += 1.0  # songs usually end on the tonic
    best = None
    for tonic in range(12):
        for minor, prof in ((False, MAJOR_PROFILE), (True, MINOR_PROFILE)):
            rot = [prof[(pc - tonic) % 12] for pc in range(12)]
            mh, mp = sum(hist) / 12, sum(rot) / 12
            num = sum((h - mh) * (r - mp) for h, r in zip(hist, rot))
            den = (sum((h - mh) ** 2 for h in hist) * sum((r - mp) ** 2 for r in rot)) ** 0.5 or 1
            if best is None or num / den > best[0]:
                best = (num / den, tonic, minor)
    return best[1], best[2]


def key_candidates(library, notes):
    """Chord shapes that belong to the song's key, with a small preference
    for the chords songs lean on most (I, IV, V)."""
    tonic, minor = find_key(notes)
    if minor:
        # i, iv, v/V, III, VI, VII, plus the V7 used in minor keys.
        degrees = {0: ("m", 0.2), 5: ("m", 0.05), 7: ("", 0.1), 3: ("", 0), 8: ("", 0), 10: ("", 0)}
        extra = {7: "7", 0: "m7", 5: "m7"}
    else:
        degrees = {0: ("", 0.2), 5: ("", 0.1), 7: ("", 0.1), 2: ("m", 0), 4: ("m", 0), 9: ("m", 0)}
        extra = {7: "7", 2: "7"}  # V7, and V7 of V
    wanted = {}
    for deg, (q, bonus) in degrees.items():
        wanted[((tonic + deg) % 12, q)] = bonus
    for deg, q in extra.items():
        wanted.setdefault(((tonic + deg) % 12, q), 0)
    out = {}
    for name in DETECT_CHORDS:
        if name not in library:
            continue
        q = name[1:].lstrip("#b")
        root = chord_root(name)
        if (root, q) in wanted:
            out[name] = (chord_pcs(library[name]), root, wanted[(root, q)])
    if len(out) < 2:  # an unusual key: fall back to every simple chord
        out = {n: (chord_pcs(library[n]), chord_root(n), 0) for n in DETECT_CHORDS if n in library}
    return out


def build_easy(bars, notes, library, unit, bpb, warnings):
    """One strum per beat, down on the first beat of the bar and then
    alternating, like the built-in songs."""
    candidates = key_candidates(library, notes)
    everything = {n: (chord_pcs(library[n]), chord_root(n), 0) for n in DETECT_CHORDS if n in library}
    annotated = any(b["chords"] for b in bars)
    unknown = set()
    segments = []  # (start, end, chord) in app beats
    current = None
    for bar in bars:
        s, e = bar["start"], bar["end"]
        if annotated:
            changes = [(s, current)] if current else []
            for t, raw in sorted(bar["chords"]):
                shape = normalize_chord(raw, library)
                if shape is None:
                    unknown.add(raw)
                    found = detect(notes, t, e, everything, current)
                    shape = found[1] if found else current
                changes.append((max(s, t), shape))
                current = shape
            for i, (t, c) in enumerate(changes):
                t_end = changes[i + 1][0] if i + 1 < len(changes) else e
                if c and t_end > t:
                    segments.append((t, t_end, c))
            continue
        whole = detect(notes, s, e, candidates, current)
        if whole is None:
            if current:
                segments.append((s, e, current))
            continue
        if bpb % 2 == 0 and bpb >= 2:
            mid = s + (e - s) / 2
            a = detect(notes, s, mid, candidates, current)
            b = detect(notes, mid, e, candidates, a[1] if a else current)
            if a and b and a[1] != b[1] and a[0] + b[0] > whole[0] + 0.25 * (e - s):
                segments += [(s, mid, a[1]), (mid, e, b[1])]
                current = b[1]
                continue
        segments.append((s, e, whole[1]))
        current = whole[1]
    if unknown:
        warnings.append("chords the app has no shape for were guessed from the notes: " + ", ".join(sorted(unknown)))

    easy = []
    for s, e, c in segments:
        b = float(s)
        while b < e - 1e-6:
            step = min(1.0, e - b)
            nxt = int(b + 1e-6) + 1
            step = min(step, nxt - b) if nxt < e else step
            in_bar = int(round(b, 4)) % bpb
            easy.append({"beat": round(b, 4), "chord": c,
                         "strum": "down" if in_bar % 2 == 0 else "up", "length": round(step, 4)})
            b += step
    return easy


# ------------------------------------------------------------- Converting

def slugify(text):
    text = text.translate(str.maketrans({
        "đ": "dj", "Đ": "Dj", "ž": "z", "Ž": "Z", "ć": "c", "Ć": "C", "č": "c", "Č": "C", "š": "s", "Š": "S"}))
    cyr = "абвгдђежзијклљмнњопрстћуфхцчџш"
    lat = ["a", "b", "v", "g", "d", "dj", "e", "z", "z", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p",
           "r", "s", "t", "c", "u", "f", "h", "c", "c", "dz", "s"]
    text = "".join(lat[cyr.index(ch.lower())] if ch.lower() in cyr else ch for ch in text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def convert(path, meta):
    ext = os.path.splitext(path)[1].lower()
    track_no = meta.get("track")
    if ext in (".gp3", ".gp4", ".gp5"):
        score = read_guitar_pro(path, track_no)
    else:
        score = read_musicxml(path, track_no)
    warnings = score.warnings
    if not score.measures:
        raise ImportError_("the score has no bars")
    measures = expand_repeats(score.measures, warnings)

    first = measures[0]
    unit, bpb = beat_unit(first.num, first.den)
    if any(beat_unit(m.num, m.den) != (unit, bpb) for m in measures):
        warnings.append("the time signature changes; the app counts the whole song in "
                        f"{first.num}/{first.den}")
    bar_len = bpb * unit

    notes = join_ties([n for m in measures for n in m.notes])
    if not notes:
        raise ImportError_("the guitar part has no notes")
    tuning = score.tuning or list(STANDARD)
    notes = assign_positions(notes, tuning, warnings)
    if not notes:
        raise ImportError_("none of the notes fit on the neck")
    assign_fingers(notes)
    chords = [c for m in measures for c in m.chords]

    # Skip empty bars at the start, and line a short pickup bar up with the
    # bar lines the app draws.
    first_note = min(n.t for n in notes)
    shift = -int(first_note // bar_len + 1e-9) * bar_len
    if first.length < bar_len - 1e-6 and first_note < first.length:
        shift = bar_len - first.length
    for n in notes:
        n.t += shift
    chords = [(t + shift, c) for t, c in chords if t + shift >= -1e-6]

    tempo = float(meta.get("tempo") or 0)
    if not tempo:
        if not score.tempo:
            warnings.append("the score has no tempo; using 90 beats per minute")
        tempo = (score.tempo or 90) / unit

    full = []
    for n in sorted(notes, key=lambda n: (n.t, n.string)):
        full.append({"beat": round(n.t / unit, 4), "string": n.string, "fret": n.fret,
                     "finger": n.finger, "length": round(max(n.dur, 0.05) / unit, 4)})

    end_beats = max(e["beat"] + e["length"] for e in full)
    n_bars = int((end_beats - 1e-6) // bpb) + 1
    first_bar = int(full[0]["beat"] // bpb)
    unit_notes = [Note(t=n.t / unit, dur=n.dur / unit, midi=n.midi) for n in notes]
    bars = []
    for b in range(first_bar, n_bars):
        s, e = b * bpb, (b + 1) * bpb
        bars.append({"start": s, "end": e,
                     "chords": [(t / unit, c) for t, c in chords if s - 1e-6 <= t / unit < e - 1e-6]})
    library = load_chords()
    easy = build_easy(bars, unit_notes, library, unit, bpb, warnings)
    # The app wants songs to end on a bar line; keep strumming the last chord.
    bar_end = -(-round(end_beats, 4) // bpb) * bpb
    b = max((e["beat"] + e["length"] for e in easy), default=bar_end)
    while easy and b < bar_end - 1e-6:
        easy.append({"beat": round(b, 4), "chord": easy[-1]["chord"],
                     "strum": "down" if int(round(b, 4)) % bpb % 2 == 0 else "up", "length": 1.0})
        b += 1

    if tuning != STANDARD:
        warnings.append("the guitar is not in standard tuning; easy-mode chord shapes assume standard tuning")

    seconds = end_beats * 60 / tempo
    onsets = len({e["beat"] for e in full})
    rate = onsets / max(seconds, 1)
    top = max(e["fret"] for e in full)
    difficulty = "easy" if rate <= 2 and top <= 5 else "hard" if rate > 4 or top > 9 else "medium"

    title = meta.get("title") or score.title or os.path.splitext(os.path.basename(path))[0]
    if isinstance(title, str):
        title = {"en": title, "sr": title}
    song_id = meta.get("id") or slugify(title.get("en") or title.get("sr") or "") or \
        slugify(os.path.splitext(os.path.basename(path))[0])
    if not re.fullmatch(r"[a-z0-9-]+", song_id or ""):
        raise ImportError_(f"'{song_id}' is not a valid id (use lowercase letters, digits and -)")

    return warnings, {
        "id": song_id,
        "title": title,
        "artist": meta.get("artist") or score.artist or "Traditional",
        "license": meta.get("license", "public-domain"),
        "source": meta.get("source") or f"Imported from {os.path.basename(path)}",
        "language": meta.get("language", "instrumental"),
        "difficulty": meta.get("difficulty") or difficulty,
        "tags": meta.get("tags", []),
        "tempo": round(tempo, 2) if tempo != int(tempo) else int(tempo),
        "timeSignature": [first.num, first.den],
        "beatsPerBar": bpb,
        "tuning": [midi_name(m) for m in reversed(tuning)],
        "capo": score.capo,
        "tracks": {"full": full, "easy": easy},
    }


def midi_name(m):
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def dump_song(song):
    """JSON with one note/chord event per line, like the other song files."""
    head = {k: v for k, v in song.items() if k != "tracks"}
    text = json.dumps(head, ensure_ascii=False, indent=2)[:-2]
    parts = []
    for name, events in song["tracks"].items():
        lines = ",\n".join("      " + json.dumps(e, ensure_ascii=False) for e in events)
        parts.append(f'    "{name}": [\n{lines}\n    ]')
    return text + ',\n  "tracks": {\n' + ",\n".join(parts) + "\n  }\n}\n"


def import_file(path, index, report):
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    sidecar = os.path.splitext(path)[0] + ".json"
    meta = {}
    if os.path.exists(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                meta = json.load(f)
        except ValueError as e:
            raise ImportError_(f"{os.path.basename(sidecar)} is not valid JSON: {e}")

    warnings, song = convert(path, meta)
    entries = index["songs"]
    mine = next((e for e in entries if e.get("importedFrom") == rel), None)
    same_id = next((e for e in entries if e["id"] == song["id"]), None)
    if same_id is not None and same_id is not mine:
        if same_id.get("importedFrom"):
            raise ImportError_(f"id '{song['id']}' is already used by {same_id['importedFrom']}; "
                               "set a different \"id\" in the sidecar file")
        if not meta.get("replace"):
            raise ImportError_(f"a song with id '{song['id']}' already exists; set a different \"id\" "
                               "in the sidecar file, or \"replace\": true to overwrite it")
        mine = same_id
    if mine is not None and mine["id"] != song["id"]:
        old_file = os.path.join(ROOT, mine["file"])
        if os.path.exists(old_file):
            os.remove(old_file)

    out = os.path.join(ROOT, f"{song['id']}.json")
    text = dump_song(song)
    old = None
    if mine is not None and os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            old = f.read()
    version = mine.get("version", 1) if mine else 1
    changed = old != text
    if mine is not None and changed:
        version += 1
    if changed:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)

    entry = {
        "id": song["id"], "file": f"{song['id']}.json", "title": song["title"],
        "artist": song["artist"], "language": song["language"], "difficulty": song["difficulty"],
        "tags": song["tags"], "version": version, "importedFrom": rel,
    }
    if mine is not None:
        entries[entries.index(mine)] = entry
    else:
        entries.append(entry)
    status = "added" if mine is None else "updated" if changed else "unchanged"
    report.append({"file": rel, "id": song["id"], "status": status, "version": version,
                   "notes": len(song["tracks"]["full"]), "strums": len(song["tracks"]["easy"]),
                   "difficulty": song["difficulty"], "warnings": warnings})
    return song


def main(argv):
    if argv:
        files = argv
    elif os.path.isdir(IMPORT_DIR):
        files = sorted(os.path.join(IMPORT_DIR, f) for f in os.listdir(IMPORT_DIR))
    else:
        files = []
    index_path = os.path.join(ROOT, "index.json")
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    report, failures = [], []
    for path in files:
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        if name.startswith(".") or name.lower() == "readme.md":
            continue
        if ext == ".json":
            stem = os.path.splitext(path)[0]
            if not any(os.path.exists(stem + e) for e in SCORE_EXTS + (".gp", ".gpx")):
                failures.append((name, "sidecar file with no score file of the same name"))
            continue
        if ext in (".gp", ".gpx"):
            failures.append((name, "Guitar Pro 6-8 files (.gpx, .gp) can't be read; in Guitar Pro use "
                                   "File > Export > Guitar Pro 5 (.gp5) or MusicXML"))
            continue
        if ext in (".ptb",):
            failures.append((name, "PowerTab files can't be read; open it in TuxGuitar or Guitar Pro "
                                   "and export as .gp5 or MusicXML"))
            continue
        if ext not in SCORE_EXTS:
            failures.append((name, f"unsupported file type '{ext}'; use .gp3/.gp4/.gp5 or MusicXML"))
            continue
        try:
            import_file(path, index, report)
        except ImportError_ as e:
            failures.append((name, str(e)))
        except Exception as e:  # a bug or a very unusual file; report it and go on
            failures.append((name, f"unexpected error: {type(e).__name__}: {e}"))

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")

    lines = ["## Song import", ""]
    if not report and not failures:
        lines.append("No files in `import/`.")
    for r in report:
        lines.append(f"- ✅ `{r['file']}` → `{r['id']}.json`: {r['status']} (version {r['version']}, "
                     f"{r['notes']} notes, {r['strums']} strums, {r['difficulty']})")
        for w in r["warnings"]:
            lines.append(f"  - ⚠️ {w}")
    for name, msg in failures:
        lines.append(f"- ❌ `{name}`: {msg}")
    text = "\n".join(lines) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"failed={len(failures)}\n")
    return 1 if failures and not os.environ.get("GITHUB_OUTPUT") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
