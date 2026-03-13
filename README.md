# MIDI-to-text-automation-project

Automates the conversion of **Logic Pro's MIDI Event List** text export into a human-readable **arrangement outline**, replacing a slow and tedious manual transcription workflow.

---

## Table of Contents

- [Overview](#overview)
- [Project Files](#project-files)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Input Formats](#input-formats)
  - [Format A — Note-first (simple)](#format-a--note-first-simple)
  - [Format B — Position-first (real Logic Pro Event List)](#format-b--position-first-real-logic-pro-event-list)
- [How It Works](#how-it-works)
- [CLI Reference](#cli-reference)
- [Output Modes](#output-modes)
  - [Per-measure mode (default)](#per-measure-mode-default)
  - [Continuous mode](#continuous-mode)
- [Chord Map](#chord-map)
- [Accidental Preference](#accidental-preference)
- [Extended Example](#extended-example)
- [Running the Tests](#running-the-tests)

---

## Overview

Logic Pro can export the MIDI Event List for any region as plain text. This project reads that text file and produces a compact, readable representation of the musical arrangement — one line per bar — showing which notes or chords fall at each rhythmic position.

**Before** (raw Logic Pro export):

```
 	  	 53 1 1 1 	 Note	 11	 C2	 79	 0 1 2 154
			 Vit. rel.			 0
 	  	 53 2 1 1 	 Note	 11	 C3	 85	 0 0 1 195
			 Vit. rel.			 0
 	  	 53 2 1 1 	 Note	 11	 E3	 78	 0 0 1 140
			 Vit. rel.			 0
```

**After** (`python parse_midi.py my_export.txt --chord-map chord_map.json`):

```
Bar  53: C  CE
```

---

## Project Files

| File | Description |
|---|---|
| `parse_midi.py` | Core parser script — reads the MIDI text export and outputs the arrangement outline |
| `chord_map.json` | Sample JSON chord-name mapping (triads and 7ths in C major / A minor). User-extensible. |
| `sample_midi_info_notes.txt` | Representative 4-bar Logic Pro Event List export for testing and onboarding |
| `test_parse_midi.py` | 42 `unittest` tests covering all key behaviours |

---

## Requirements

- **Python 3.8+** (standard library only — no third-party packages required)

---

## Quick Start

1. **Export the MIDI Event List from Logic Pro**
   - Open the Piano Roll or Score for the desired region
   - Choose *File → Export → MIDI Event List as Text…*
   - Save the file (e.g. `midi_info_notes.txt`) alongside `parse_midi.py`

2. **Run the parser**

   ```bash
   python parse_midi.py
   # or with a custom file name:
   python parse_midi.py my_export.txt
   ```

3. **Optionally supply a chord map** to get chord names instead of raw note letters:

   ```bash
   python parse_midi.py --chord-map chord_map.json
   ```

---

## Input Formats

The parser automatically detects and handles both export variants from Logic Pro.

### Format A — Note-first (simple)

Used in user-assembled files or earlier Logic Pro versions. Each note line begins with `Note`:

```
Note	1 1 1 1	C3	100	0 1 0 0
Note	1 1 1 1	E3	100	0 1 0 0
Note	1 1 1 1	G3	100	0 1 0 0
Note	1 3 1 1	G3	85	0 0 2 0
```

Column layout: `Note  <bar> <beat> <div> <tick>  <pitch>  <velocity>  <duration>`

### Format B — Position-first (real Logic Pro Event List)

Used by current versions of Logic Pro. The position comes first, followed by `Note` and a MIDI channel number. `Vit. rel.` continuation lines (velocity release info) are automatically skipped.

```
 	  	 53 1 1 1 	 Note	 11	 C2	 79	 0 1 2 154
			 Vit. rel.			 0
 	  	 53 1 3 1 	 Note	 11	 G2	 76	 0 0 1 97
			 Vit. rel.			 0
 	  	 53 4 1 1 	 Note	 11	 F♯3	 73	 0 0 2 18
			 Vit. rel.			 0
```

Column layout: `<bar> <beat> <div> <tick>  Note  <channel>  <pitch>  <velocity>  <duration>`

> **Unicode accidentals** (`♯`, `♭`) are fully supported in both formats.

---

## How It Works

1. **Parse** — Each note line is read and its position (`bar`, `beat`, `division`) is extracted.
2. **Grid mapping** — The position is mapped to a 16-slot-per-bar grid (1/16-note resolution):
   - Beat 1 → slots 0–3
   - Beat 2 → slots 4–7
   - Beat 3 → slots 8–11
   - Beat 4 → slots 12–15
3. **Slot rendering** — Notes sounding at the same slot are concatenated (e.g. C + E + G → `CEG`). If a chord-map entry matches the sorted note names, the chord label is shown instead.
4. **Bar assembly** — Empty slots become a single space, preserving visual rhythm. Trailing spaces are stripped.
5. **Output** — Bars are printed one per line (default) or joined with `|` separators.

---

## CLI Reference

```
python parse_midi.py [INPUT] [--chord-map FILE] [--flats] [--continuous] [--output FILE]
```

| Argument | Default | Description |
|---|---|---|
| `INPUT` | `midi_info_notes.txt` | Path to the MIDI text export file |
| `--chord-map FILE` | `chord_map.json` (if it exists) | Path to a JSON chord-name mapping file |
| `--flats` | off | Render accidentals as flats (`Bb`) instead of sharps (`A#`) |
| `--continuous` | off | Output a single continuous line with `\|` bar separators instead of one line per bar |
| `--output FILE` | stdout | Write result to a file instead of printing to the terminal |

---

## Output Modes

### Per-measure mode (default)

Each bar is printed on its own labelled line. Empty 1/16-note slots are rendered as spaces, so the rhythmic shape of the bar is visible at a glance.

```
Bar   1: C       G
Bar   2: Dm       F
Bar   3: Am       E
Bar   4: G       D
```

### Continuous mode

All bars are joined on a single line separated by `|`. Useful for a compact overview.

```bash
python parse_midi.py --continuous
```

```
C       G | Dm       F | Am       E | G       D
```

---

## Chord Map

`chord_map.json` maps **sorted, concatenated note names** (without octave) to chord labels.

```json
{
  "CEG":   "C",
  "ADF":   "Dm",
  "BEG":   "Em",
  "ACF":   "F",
  "BDG":   "G",
  "ACE":   "Am",
  "BDF":   "Bdim",
  "BCEG":  "Cmaj7",
  "ACDF":  "Dm7",
  "ABEG":  "Em7",
  "ACEF":  "Fmaj7",
  "BDFG":  "G7",
  "ABCE":  "Am7",
  "ABDF":  "Bm7b5"
}
```

**How to extend it:**
- Sort the note names alphabetically (no spaces, no octave numbers), e.g. D + F# + A → `ADF#`.
- Add an entry: `"ADF#": "D"`.
- Any notes that don't match a chord-map entry are displayed as raw concatenated note names.

---

## Accidental Preference

By default the parser renders accidentals as **sharps** (`C#`, `F#`, `A#`, …). Pass `--flats` to use the flat equivalents (`Db`, `Gb`, `Bb`, …):

```bash
python parse_midi.py --flats
```

---

## Extended Example

**Input** (`sample_midi_info_notes.txt` — Format A, 4 bars):

```
Note	1 1 1 1	C3	100	0 1 0 0
Note	1 1 1 1	E3	100	0 1 0 0
Note	1 1 1 1	G3	100	0 1 0 0
Note	1 3 1 1	G3	85	0 0 2 0
Note	2 1 1 1	D3	100	0 1 0 0
Note	2 1 1 1	F3	100	0 1 0 0
Note	2 1 1 1	A3	100	0 1 0 0
Note	2 3 1 1	F3	90	0 0 2 0
Note	3 1 1 1	A3	100	0 1 0 0
Note	3 1 1 1	C4	100	0 1 0 0
Note	3 1 1 1	E4	100	0 1 0 0
Note	3 3 1 1	E4	88	0 0 2 0
Note	4 1 1 1	G3	100	0 1 0 0
Note	4 1 1 1	B3	100	0 1 0 0
Note	4 1 1 1	D4	100	0 1 0 0
Note	4 3 1 1	D4	90	0 0 2 0
```

**Output** (no chord map — `chord_map.json` absent or not specified):

```bash
python parse_midi.py sample_midi_info_notes.txt --chord-map /dev/null
```

```
Bar   1: CEG       G
Bar   2: ADF       F
Bar   3: ACE       E
Bar   4: BDG       D
```

**Output** (with chord map):

```bash
python parse_midi.py sample_midi_info_notes.txt --chord-map chord_map.json
```

```
Bar   1: C       G
Bar   2: Dm       F
Bar   3: Am       E
Bar   4: G       D
```

**Real Logic Pro export** (Format B, bars 53–60, with `Vit. rel.` continuation lines):

```bash
python parse_midi.py real_export.txt
```

```
Bar  53: C G CE G D A DF# A
Bar  54: G D BG CG BG   G
Bar  55: C G CE G D A DF# A
Bar  56: G D BG CG BG   G
Bar  57: C G CE G D A DF# A
Bar  58: E B EG B A A C#E A
Bar  59: A A C AE
Bar  60: ACDF#
```

---

## Running the Tests

```bash
python -m pytest test_parse_midi.py -v
# or
python test_parse_midi.py
```

42 tests cover pitch normalisation, grid positioning, slot rendering, chord lookup, both input formats, and CLI integration.
