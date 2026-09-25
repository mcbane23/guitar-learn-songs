#!/usr/bin/env python3
"""Round-trip check for import_songs.py: writes some of the existing songs out
as Guitar Pro 5 and MusicXML files, imports them again and compares the notes.

    python3 tools/test_import_songs.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_songs as imp  # noqa: E402

ROOT = imp.ROOT
SONGS = ["greensleeves", "ode-to-joy", "jingle-bells", "silent-night", "amazing-grace"]
PIECES = [4, 3, 2, 1.5, 1, 0.75, 0.5, 0.375, 0.25, 0.125]
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def load(song_id):
    with open(os.path.join(ROOT, f"{song_id}.json"), encoding="utf-8") as f:
        return json.load(f)


def unit_of(song):
    return imp.beat_unit(*song["timeSignature"])[0]


def split_pieces(length):
    out = []
    while length > 1e-6:
        p = next(p for p in PIECES if p <= length + 1e-6)
        out.append(p)
        length -= p
    return out


def bar_items(song):
    """[(bar, [(start_q, len_q, note or None)])] in quarter notes, split at bar lines."""
    unit = unit_of(song)
    num, den = song["timeSignature"]
    bar_q = num * 4 / den
    notes = [(e["beat"] * unit, e["length"] * unit, e) for e in song["tracks"]["full"]]
    end = max(t + d for t, d, _ in notes)
    n_bars = int((end - 1e-6) // bar_q) + 1
    chords = {}
    for e in song["tracks"]["easy"]:
        t = e["beat"] * unit
        if not chords or list(chords.values())[-1] != e["chord"]:
            chords[t] = e["chord"]
    bars = []
    for b in range(n_bars):
        s, e = b * bar_q, (b + 1) * bar_q
        items, t = [], s
        for nt, nd, n in notes:
            if nt + nd <= s + 1e-6 or nt >= e - 1e-6:
                continue
            start = max(nt, s)
            if start > t + 1e-6:
                items.append((t, start - t, None, False, False))
            stop = min(nt + nd, e)
            items.append((start, stop - start, n, nt < s - 1e-6, nt + nd > e + 1e-6))
            t = stop
        if t < e - 1e-6:
            items.append((t, e - t, None, False, False))
        bars.append((items, [(ct, c) for ct, c in chords.items() if s <= ct < e]))
    return bars


def write_gp5(song, path):
    import guitarpro as gp
    num, den = song["timeSignature"]
    g = gp.Song(title=song["title"]["en"], artist=song["artist"], tempo=round(song["tempo"] * unit_of(song)))
    track = g.tracks[0]
    bars = bar_items(song)
    while len(g.measureHeaders) < len(bars):
        g.newMeasure()
    t0 = 960
    for i, h in enumerate(g.measureHeaders):
        h.number = i + 1
        h.start = t0
        h.timeSignature = gp.TimeSignature(numerator=num, denominator=gp.Duration(value=den))
        t0 += h.length
    for (items, chords), measure in zip(bars, track.measures):
        voice = measure.voices[0]
        for start, length, n, tied, cont in items:
            first = True
            for piece in split_pieces(length):
                dur = gp.Duration.fromTime(round(piece * 960))
                beat = gp.Beat(voice, duration=dur,
                               status=gp.BeatStatus.normal if n else gp.BeatStatus.rest)
                if n:
                    note = gp.Note(beat, value=n["fret"], string=n["string"],
                                   type=gp.NoteType.tie if (tied or not first) else gp.NoteType.normal)
                    note.effect.leftHandFinger = gp.Fingering(n["finger"] if n["fret"] else -1)
                    beat.notes.append(note)
                for ct, c in chords:
                    if abs(ct - start) < 1e-6 and first:
                        beat.effect.chord = gp.Chord(length=6, name=c, firstFret=1, strings=[-1] * 7, show=True, newFormat=True, add=False)
                voice.beats.append(beat)
                start += piece
                first = False
    gp.write(g, path, version=(5, 1, 0))


XML_TYPES = {4: "whole", 3: "half", 2: "half", 1.5: "quarter", 1: "quarter", 0.75: "eighth",
             0.5: "eighth", 0.375: "16th", 0.25: "16th", 0.125: "32nd"}


def write_musicxml(song, path):
    """Standard notation only (no tab), written an octave up like guitar music."""
    num, den = song["timeSignature"]
    tuning = [64, 59, 55, 50, 45, 40]
    div = 8
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<score-partwise version="3.1">',
           f'<work><work-title>{song["title"]["en"]}</work-title></work>',
           f'<identification><creator type="composer">{song["artist"]}</creator></identification>',
           '<part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>',
           '<part id="P1">']
    for b, (items, chords) in enumerate(bar_items(song)):
        out.append(f'<measure number="{b + 1}">')
        if b == 0:
            out.append(f'<attributes><divisions>{div}</divisions><time><beats>{num}</beats>'
                       f'<beat-type>{den}</beat-type></time><clef><sign>G</sign><line>2</line>'
                       '<clef-octave-change>-1</clef-octave-change></clef>'
                       '<transpose><diatonic>0</diatonic><chromatic>0</chromatic>'
                       '<octave-change>-1</octave-change></transpose></attributes>')
            out.append(f'<direction><sound tempo="{song["tempo"] * unit_of(song)}"/></direction>')
        for start, length, n, tied, cont in items:
            for ct, c in chords:
                if abs(ct - start) < 1e-6:
                    root, rest = (c[:2], c[2:]) if len(c) > 1 and c[1] in "#b" else (c[0], c[1:])
                    kind = {"": "major", "m": "minor", "7": "dominant", "m7": "minor-seventh"}.get(rest, "major")
                    out.append(f'<harmony><root><root-step>{root[0]}</root-step></root><kind>{kind}</kind></harmony>')
            pieces = split_pieces(length)
            for i, piece in enumerate(pieces):
                if n is None:
                    out.append(f'<note><rest/><duration>{round(piece * div)}</duration><voice>1</voice></note>')
                    continue
                midi = tuning[n["string"] - 1] + n["fret"] + 12
                step = NAMES[midi % 12]
                ties = ""
                if tied or i > 0:
                    ties += '<tie type="stop"/>'
                if i < len(pieces) - 1 or cont:
                    ties += '<tie type="start"/>'
                alter = "<alter>1</alter>" if "#" in step else ""
                out.append(f'<note><pitch><step>{step[0]}</step>{alter}<octave>{midi // 12 - 1}</octave></pitch>'
                           f'<duration>{round(piece * div)}</duration>{ties}<voice>1</voice>'
                           f'<type>{XML_TYPES[piece]}</type></note>')
        out.append('</measure>')
    out += ['</part>', '</score-partwise>']
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def pitches(song):
    tuning = [64, 59, 55, 50, 45, 40]
    return [(e["beat"], round(e["length"], 3), tuning[e["string"] - 1] + e["fret"]) for e in song["tracks"]["full"]]


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    return ok


def main():
    good = True
    tmp = tempfile.mkdtemp()
    for song_id in SONGS:
        song = load(song_id)
        want = pitches(song)
        bpb = song["beatsPerBar"]
        # The importer drops empty bars before the first note, so compare from the first bar with notes.
        skip = int(song["tracks"]["full"][0]["beat"] // bpb) * bpb
        want = [(round(b - skip, 4), d, m) for b, d, m in want]

        gp_path = os.path.join(tmp, f"{song_id}.gp5")
        write_gp5(song, gp_path)
        warnings, got = imp.convert(gp_path, {})
        good &= check(f"{song_id}.gp5 notes", pitches(got) == want, _diff(pitches(got), want))
        exact = [(e["string"], e["fret"]) for e in got["tracks"]["full"]] == \
            [(e["string"], e["fret"]) for e in song["tracks"]["full"]]
        good &= check(f"{song_id}.gp5 strings and frets kept", exact)
        end = max(e["beat"] + e["length"] for e in got["tracks"]["full"] + got["tracks"]["easy"])
        good &= check(f"{song_id}.gp5 ends on a bar line", abs(end % bpb) < 1e-6, f"ends at {end}")
        good &= check(f"{song_id}.gp5 tempo", abs(got["tempo"] - song["tempo"]) < 1, f"{got['tempo']}")
        chords_in = [e["chord"] for e in song["tracks"]["easy"]]
        chords_out = [e["chord"] for e in got["tracks"]["easy"]]
        good &= check(f"{song_id}.gp5 chords", _runs(chords_in) == _runs(chords_out),
                      f"{_runs(chords_out)} vs {_runs(chords_in)}")

        xml_path = os.path.join(tmp, f"{song_id}.musicxml")
        write_musicxml(song, xml_path)
        warnings, got = imp.convert(xml_path, {})
        good &= check(f"{song_id}.musicxml notes", pitches(got) == want, _diff(pitches(got), want))
        good &= check(f"{song_id}.musicxml fingers valid",
                      all((e["fret"] == 0) == (e["finger"] == 0) and 0 <= e["finger"] <= 4
                          for e in got["tracks"]["full"]))

        # Without chord names the importer has to guess them from the notes.
        song_nc = json.loads(json.dumps(song))
        song_nc["tracks"]["easy"] = []
        write_gp5(song_nc, gp_path)
        warnings, got = imp.convert(gp_path, {})
        good &= check(f"{song_id} without chord names has no chord mode", got["tracks"]["easy"] == [])
        warnings, got = imp.convert(gp_path, {"guessChords": True})
        good &= check(f"{song_id} guessed chords exist",
                      bool(got["tracks"]["easy"]) and all(e["chord"] in imp.load_chords() for e in got["tracks"]["easy"]))
        print("     guessed:", " ".join(_runs([e["chord"] for e in got["tracks"]["easy"]])[:12]))
    print("OK" if good else "FAILED")
    return 0 if good else 1


def _runs(xs):
    out = []
    for x in xs:
        if not out or out[-1] != x:
            out.append(x)
    return out


def _diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"event {i}: got {x}, want {y}"
    return f"got {len(a)} events, want {len(b)}"


if __name__ == "__main__":
    sys.exit(main())
