#!/usr/bin/env python3
"""
parse_midi.py
=============
MVP parser: Logic Pro MIDI note-text export → readable arrangement outline.

Input
-----
A plain-text file (default: midi_info_notes.txt) produced by Logic Pro's
Event List export.  Each note line looks like::

    Note    <bar> <beat> <div> <tick>    <pitch+octave>    <velocity>    <duration>

e.g.::

    Note    1 1 1 1    C3    100    0 1 0 0

Output
------
One line per bar (default) or a single continuous line, showing note groups
at their rhythmic positions within a 16-subdivision-per-bar grid.
Simultaneous notes are concatenated without spaces (e.g. ``CEG``); empty
grid slots produce a single space character so that rhythm is legible.

Chord names can optionally replace note clusters when a ``chord_map.json``
mapping file is provided.

Usage
-----
    python parse_midi.py [INPUT] [--chord-map FILE] [--flats] [--continuous]
                         [--output FILE]

Extend this script as the project evolves (new features, richer input
formats, additional output styles, etc.).
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Grid constants ─────────────────────────────────────────────────────────────

DIVISIONS_PER_BEAT: int = 4   # 1/16-note grid (4 divisions × 4 beats = 16/bar)
BEATS_PER_BAR: int = 4
SLOTS_PER_BAR: int = DIVISIONS_PER_BEAT * BEATS_PER_BAR  # 16

# ── Note name tables ───────────────────────────────────────────────────────────

_SHARP_NAMES: List[str] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
]
_FLAT_NAMES: List[str] = [
    "C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B",
]

# Map every common spelling (including Unicode accidentals) → semitone index
_ENHARMONIC: Dict[str, int] = {
    "C": 0, "B#": 0,
    "C#": 1, "Db": 1, "C♯": 1, "D♭": 1,
    "D": 2,
    "D#": 3, "Eb": 3, "D♯": 3, "E♭": 3,
    "E": 4, "Fb": 4,
    "F": 5, "E#": 5,
    "F#": 6, "Gb": 6, "F♯": 6, "G♭": 6,
    "G": 7,
    "G#": 8, "Ab": 8, "G♯": 8, "A♭": 8,
    "A": 9,
    "A#": 10, "Bb": 10, "A♯": 10, "B♭": 10,
    "B": 11, "Cb": 11,
}

# ── Parsing helpers ────────────────────────────────────────────────────────────

# Format A – "Note-first" (simpler / user-constructed files):
#   Note  <bar> <beat> <div> <tick>  <pitch+octave>  <velocity>  ...
# e.g.:  Note    1 1 1 1    C3    100    0 1 0 0
_NOTE_RE_A = re.compile(
    r"^Note"
    r"\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"    # bar beat div tick
    r"\s+([A-Ga-g][#b♯♭]?\d+)",            # pitch + octave
    re.IGNORECASE,
)

# Format B – "Position-first" (real Logic Pro Event List export):
#   <bar> <beat> <div> <tick>  Note  <channel>  <pitch+octave>  <velocity>  ...
# e.g.:  53 1 1 1    Note    11    C2    79    0 1 2 154
# Lines may be preceded by arbitrary whitespace / tab characters.
_NOTE_RE_B = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"   # bar beat div tick
    r"\s+Note"                              # event type
    r"\s+\d+"                              # MIDI channel (ignored)
    r"\s+([A-Ga-g][#b♯♭]?\d+)",            # pitch + octave
    re.IGNORECASE,
)

# Capture only the letter + accidental from a pitch string like "F#3"
_PITCH_HEAD = re.compile(r"^([A-Ga-g][#b♯♭]?)")


def _parse_pitch(pitch_str: str, use_flats: bool = False) -> str:
    """Strip octave number and normalise accidentals.

    Examples
    --------
    >>> _parse_pitch("C3")
    'C'
    >>> _parse_pitch("F#3")
    'F#'
    >>> _parse_pitch("F♯3")
    'F#'
    >>> _parse_pitch("Bb4", use_flats=True)
    'Bb'
    """
    m = _PITCH_HEAD.match(pitch_str)
    if not m:
        return pitch_str  # unknown – pass through unchanged

    raw = m.group(1)
    # Normalise Unicode accidentals to ASCII
    raw = raw.replace("♯", "#").replace("♭", "b")
    # Ensure upper-case letter
    raw = raw[0].upper() + raw[1:]

    semitone = _ENHARMONIC.get(raw)
    if semitone is None:
        return raw  # unrecognised spelling – pass through

    table = _FLAT_NAMES if use_flats else _SHARP_NAMES
    return table[semitone]


def _position_to_slot(bar: int, beat: int, division: int) -> Tuple[int, int]:
    """Convert a Logic Pro position to (measure_0indexed, slot_0indexed).

    Within a bar there are ``SLOTS_PER_BAR`` (16) equal grid slots.

    Parameters
    ----------
    bar:      1-based measure number
    beat:     1-based beat within the bar (1–4 in 4/4)
    division: 1-based subdivision within the beat (1–4 at 1/16-note resolution)
    """
    measure = bar - 1
    slot = (beat - 1) * DIVISIONS_PER_BEAT + (division - 1)
    return measure, slot


# ── File I/O ───────────────────────────────────────────────────────────────────

EventMap = Dict[Tuple[int, int], List[str]]  # (measure, slot) → raw pitches


def parse_file(path: Path) -> EventMap:
    """Parse a Logic Pro MIDI text export and return an event map.

    Supports two export formats automatically:

    * **Format A** – "Note-first" (simple / user-assembled files)::

          Note    1 1 1 1    C3    100    0 1 0 0

    * **Format B** – "Position-first" (real Logic Pro Event List)::

          53 1 1 1    Note    11    C2    79    0 1 2 154

    ``Vit. rel.`` continuation lines and all other non-Note lines are skipped.

    Each entry maps ``(measure_0indexed, slot_0indexed)`` to a list of raw
    pitch strings (with octave, e.g. ``["C3", "E3", "G3"]``).
    """
    events: EventMap = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            m = _NOTE_RE_A.match(line) or _NOTE_RE_B.match(line)
            if not m:
                continue
            bar, beat, div = int(m.group(1)), int(m.group(2)), int(m.group(3))
            pitch = m.group(5)
            measure, slot = _position_to_slot(bar, beat, div)
            events[(measure, slot)].append(pitch)
    return events


def load_chord_map(path: Optional[Path]) -> Dict[str, str]:
    """Load an optional JSON chord-name mapping.

    The mapping keys must be sorted, concatenated note names (without octave),
    e.g. ``"CEG"`` for C major, ``"ADF"`` for D minor.  The values are the
    human-readable chord labels to display.

    Returns an empty dict when *path* is ``None`` or does not exist.
    """
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Rendering ──────────────────────────────────────────────────────────────────

def _notes_key(note_names: List[str]) -> str:
    """Sorted concatenation of note names used as a chord-map lookup key."""
    return "".join(sorted(set(note_names)))


def _render_slot(
    raw_pitches: List[str],
    chord_map: Dict[str, str],
    use_flats: bool,
) -> str:
    """Return the display token for one grid slot.

    Simultaneous notes are concatenated without spaces (e.g. ``CEG``).
    If the resulting key exists in *chord_map* the chord name is returned
    instead.
    """
    names = [_parse_pitch(p, use_flats) for p in raw_pitches]
    key = _notes_key(names)
    if key in chord_map:
        return chord_map[key]
    # Concatenate sorted unique note names, no spaces
    return "".join(sorted(set(names)))


def _render_measure(
    measure: int,
    events: EventMap,
    chord_map: Dict[str, str],
    use_flats: bool,
) -> str:
    """Build the token string for a single measure.

    Each of the 16 grid slots is either a note/chord token or a single space.
    Trailing spaces are stripped so lines stay compact.
    """
    parts: List[str] = []
    for slot in range(SLOTS_PER_BAR):
        key = (measure, slot)
        if key in events:
            parts.append(_render_slot(events[key], chord_map, use_flats))
        else:
            parts.append(" ")
    return "".join(parts).rstrip()


def build_output(
    events: EventMap,
    chord_map: Dict[str, str],
    use_flats: bool,
    per_measure: bool,
) -> str:
    """Produce the final text arrangement outline.

    Parameters
    ----------
    events:      event map returned by :func:`parse_file`
    chord_map:   chord-name mapping (may be empty)
    use_flats:   render accidentals as flats rather than sharps
    per_measure: ``True`` → one labelled line per bar;
                 ``False`` → single continuous line with bars separated by ``|``
    """
    if not events:
        return ""

    measures_used = sorted({m for (m, _) in events})

    if per_measure:
        lines = [
            f"Bar {m + 1:>3}: {_render_measure(m, events, chord_map, use_flats)}"
            for m in measures_used
        ]
        return "\n".join(lines)

    # Continuous mode: join bars with a pipe separator
    segments = [
        _render_measure(m, events, chord_map, use_flats)
        for m in measures_used
    ]
    return " | ".join(segments)


# ── CLI entry point ────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse_midi",
        description=(
            "Parse a Logic Pro MIDI text export (midi_info_notes.txt) and "
            "produce a readable music arrangement outline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  # Basic usage (looks for midi_info_notes.txt in the current directory):
  python parse_midi.py

  # Custom input file and chord map:
  python parse_midi.py my_song.txt --chord-map my_chords.json

  # Use flats instead of sharps:
  python parse_midi.py --flats

  # Output a single continuous line:
  python parse_midi.py --continuous

  # Write result to a file:
  python parse_midi.py --output arrangement.txt
""",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="midi_info_notes.txt",
        help="Path to the MIDI text export (default: midi_info_notes.txt)",
    )
    parser.add_argument(
        "--chord-map",
        metavar="FILE",
        default=None,
        help="Path to JSON chord-name mapping (default: chord_map.json if it exists)",
    )
    parser.add_argument(
        "--flats",
        action="store_true",
        help="Render accidentals as flats (Bb) rather than sharps (A#)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Emit a single continuous line instead of one line per bar",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point.  Returns an exit code (0 = success)."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1

    chord_map_path = Path(args.chord_map) if args.chord_map is not None else Path("chord_map.json")
    if args.chord_map is not None and not chord_map_path.exists():
        print(f"Error: chord map file not found: {chord_map_path}", file=sys.stderr)
        return 1

    events = parse_file(input_path)
    chord_map = load_chord_map(chord_map_path)
    result = build_output(
        events,
        chord_map,
        use_flats=args.flats,
        per_measure=not args.continuous,
    )

    if args.output:
        Path(args.output).write_text(result + "\n", encoding="utf-8")
        print(f"Arrangement written to: {args.output}")
    else:
        print(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
