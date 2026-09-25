# Guitar Learn songs

Public-domain song files for the Guitar Learn app, published at
https://mcbane23.github.io/guitar-learn-songs/ on every push to `main`.
The app downloads `index.json`, `chords.json` and any new or updated song
files, and keeps them on the device for offline use.

## Adding a song from Guitar Pro or MusicXML

The easy way. Most tab sites and notation programs can save one of these.

1. Put the file in `import/`: Guitar Pro 3-5 (`.gp3`, `.gp4`, `.gp5`) or
   MusicXML (`.musicxml`, `.xml`, `.mxl`). On github.com you can use
   **Add file > Upload files** inside the `import` folder.
   - Guitar Pro 6-8 files (`.gpx`, `.gp`): in Guitar Pro use
     **File > Export > Guitar Pro 5** or **MusicXML** first.
   - PowerTab (`.ptb`): open it in TuxGuitar or Guitar Pro and export as `.gp5`.
2. Optionally add a file with the same name ending in `.json` to set the
   title, tags and so on (see below).
3. Commit to `main`. The **Publish songs** workflow converts the file, saves
   `<id>.json` and the new `index.json` entry back to the repository, and
   publishes it. Its run summary lists every imported song with any warnings.

To fix an imported song, change the score file (or its `.json` file) and push
it again: the same song is updated and its version goes up, so the app
downloads the new one. Pushes to a pull request run the import as a check
without publishing anything.

What the importer does:

- **Full track**: the guitar part note by note, with the strings and frets from
  the tab. Scores without tab get the easiest positions. Fingers come from the
  file when it has them, otherwise one finger per fret. The app shows frets
  0-12, so higher notes are moved down the neck or left out (with a warning).
- **Easy track**: one strum per beat. Chord names in the score are used when
  the app has a shape for them (`D/F#` becomes `D`, `G9` becomes `G7`, and so
  on). Otherwise the chords are guessed from the notes, using chords that fit
  the song's key.
- Repeats and 1st/2nd endings are played out, empty bars at the start are
  dropped and a pickup bar lines up with the bar lines.
- The guitar track is the first 6-string track (Guitar Pro) or the part with
  tab or "guitar" in its name (MusicXML); set `track` to choose another.
- Difficulty is estimated from how fast the notes go and how high they are.

### The optional .json file

`import/My Song.gp5` can have `import/My Song.json` next to it. Every field is
optional:

```json
{
  "id": "moja-pesma",
  "title": {"en": "My Song", "sr": "Moja pesma"},
  "artist": "Traditional",
  "difficulty": "easy",
  "tags": ["serbian-folk", "beginner"],
  "source": "Traditional Serbian",
  "track": 2,
  "tempo": 90
}
```

- `id`: the song's file name and id. Defaults to the title, e.g. `oj-djurdjevdane`.
- `title`: defaults to the title in the score, used for both languages.
- `tags`: `beginner`, `kids` and `serbian-folk` put the song in those rows on the home screen.
- `difficulty`: `easy`, `medium` or `hard`, if the estimate is wrong.
- `track`: which track or part to use, counting from 1.
- `tempo`: beats per minute, if the score has none or it is wrong.
- `replace`: `true` lets an imported song overwrite a hand-made song with the same id.

To check an import on your own computer: `pip install pyguitarpro==0.11`, then
`python3 tools/import_songs.py` and `python3 tools/check_songs.py`.

## Adding or updating a song by hand


1. Add `<id>.json` (format: see `docs/PLAN.md` section 5 in the app repo, or copy an existing file).
2. Add an entry for it to `index.json`. To update an existing song, raise its `version`.
3. Push to `main`. The app picks it up the next time it looks for new songs.

Only add songs that are in the public domain; record the source in the song's `source` field.
