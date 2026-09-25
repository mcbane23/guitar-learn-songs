# Guitar Learn songs

Public-domain song files for the Guitar Learn app, published at
https://mcbane23.github.io/guitar-learn-songs/ on every push to `main`.
The app downloads `index.json`, `chords.json` and any new or updated song
files, and keeps them on the device for offline use.

## Adding or updating a song

1. Add `<id>.json` (format: see `docs/PLAN.md` section 5 in the app repo, or copy an existing file).
2. Add an entry for it to `index.json`. To update an existing song, raise its `version`.
3. Push to `main`. The app picks it up the next time it looks for new songs.

Only add songs that are in the public domain; record the source in the song's `source` field.
