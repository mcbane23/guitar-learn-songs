#!/usr/bin/env python3
"""Checks index.json, chords.json and every song file with the same rules as
the app's own song tests, so a broken song never gets published.

    python3 tools/check_songs.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    errors = []

    def err(where, msg):
        errors.append(f"{where}: {msg}")

    with open(os.path.join(ROOT, "chords.json"), encoding="utf-8") as f:
        chords = json.load(f)["chords"]
    for name, shape in chords.items():
        if len(shape["frets"]) != 6 or len(shape["fingers"]) != 6:
            err(f"chord {name}", "needs 6 frets and 6 fingers")
        elif all(fr < 0 for fr in shape["frets"]):
            err(f"chord {name}", "plays no strings")
        else:
            for fr, fi in zip(shape["frets"], shape["fingers"]):
                if fr > 0 and not 1 <= fi <= 4:
                    err(f"chord {name}", "a pressed string needs finger 1-4")

    with open(os.path.join(ROOT, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    ids = set()
    for e in index["songs"]:
        where = e.get("file", e.get("id"))
        if e["id"] in ids:
            err(where, f"id '{e['id']}' is listed twice")
        ids.add(e["id"])
        if not e.get("title", {}).get("en") or not e.get("title", {}).get("sr"):
            err(where, "needs an English and a Serbian title")
        try:
            with open(os.path.join(ROOT, e["file"]), encoding="utf-8") as f:
                song = json.load(f)
        except (OSError, ValueError) as ex:
            err(where, f"cannot read: {ex}")
            continue
        if song.get("id") != e["id"]:
            err(where, "id in the file does not match index.json")
        full = song.get("tracks", {}).get("full", [])
        easy = song.get("tracks", {}).get("easy", [])
        if not full or not easy:
            err(where, "needs both a full and an easy track")
            continue
        bpb = song.get("beatsPerBar") or song["timeSignature"][0]
        end = max(ev["beat"] + ev.get("length", 1) for ev in full + easy)
        if abs(end / bpb - round(end / bpb)) > 1e-3:
            err(where, f"song should end on a bar line (ends at beat {end}, {bpb} beats per bar)")
        for ev in full:
            if not 1 <= ev["string"] <= 6 or not 0 <= ev["fret"] <= 12 or not 0 <= ev.get("finger", 0) <= 4:
                err(where, f"bad note at beat {ev['beat']}: {ev}")
            elif (ev["fret"] == 0) != (ev.get("finger", 0) == 0):
                err(where, f"open strings need finger 0 and pressed ones 1-4, beat {ev['beat']}")
            if ev.get("length", 1) <= 0:
                err(where, f"note at beat {ev['beat']} has no length")
        for ev in easy:
            if ev["chord"] not in chords:
                err(where, f"chord {ev['chord']} is missing from chords.json")

    for line in errors:
        print("ERROR", line)
    print(f"{len(index['songs'])} songs checked, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
