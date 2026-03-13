"""
test_parse_midi.py
==================
Unit tests for parse_midi.py.

Run with:
    python -m pytest test_parse_midi.py -v
or simply:
    python test_parse_midi.py
"""

import json
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# Import the module under test
import parse_midi as pm


class TestMidiPitchNumber(unittest.TestCase):
    """_midi_pitch_number: compute MIDI pitch integer from raw pitch string."""

    def test_middle_c(self):
        self.assertEqual(pm._midi_pitch_number("C4"), 60)

    def test_g3(self):
        self.assertEqual(pm._midi_pitch_number("G3"), 55)

    def test_b3(self):
        self.assertEqual(pm._midi_pitch_number("B3"), 59)

    def test_c4_higher_than_b3(self):
        self.assertGreater(pm._midi_pitch_number("C4"), pm._midi_pitch_number("B3"))

    def test_g3_lower_than_b3(self):
        self.assertLess(pm._midi_pitch_number("G3"), pm._midi_pitch_number("B3"))

    def test_sharp(self):
        self.assertEqual(pm._midi_pitch_number("F#3"), pm._midi_pitch_number("Gb3"))

    def test_unicode_sharp(self):
        self.assertEqual(pm._midi_pitch_number("F♯3"), pm._midi_pitch_number("F#3"))

    def test_low_octave(self):
        # C2 = (2+1)*12 + 0 = 36
        self.assertEqual(pm._midi_pitch_number("C2"), 36)

    def test_unknown_returns_zero(self):
        self.assertEqual(pm._midi_pitch_number("?!"), 0)


class TestNoteOrdering(unittest.TestCase):
    """_render_slot: simultaneous notes must be ordered by MIDI pitch, not name."""

    def test_gbce_in_pitch_order(self):
        """G3(55) < B3(59) < C4(60) < E4(64) — must NOT be alphabetical BCEG."""
        result = pm._render_slot(["G3", "B3", "C4", "E4"], {}, False)
        self.assertEqual(result, "GBCE")

    def test_gbce_regardless_of_input_order(self):
        """Input order must not affect the pitch-ordered output."""
        result = pm._render_slot(["E4", "C4", "B3", "G3"], {}, False)
        self.assertEqual(result, "GBCE")

    def test_g_major_triad_pitch_order(self):
        """G3(55) < B3(59) < D4(62) — must be GBD, not BDG (alphabetical)."""
        result = pm._render_slot(["B3", "D4", "G3"], {}, False)
        self.assertEqual(result, "GBD")

    def test_c_major_triad_same_in_both_orders(self):
        """C3(48) < E3(52) < G3(55) — pitch order == alphabetical order here."""
        result = pm._render_slot(["C3", "E3", "G3"], {}, False)
        self.assertEqual(result, "CEG")

    def test_a_minor_across_octave(self):
        """A3(57) < C4(60) < E4(64) — pitch order gives ACE."""
        result = pm._render_slot(["A3", "C4", "E4"], {}, False)
        self.assertEqual(result, "ACE")

    def test_ordering_with_flats(self):
        """G3 < Bb3 < D4 — rendered as flats, must be GBbD."""
        result = pm._render_slot(["G3", "A#3", "D4"], {}, use_flats=True)
        self.assertEqual(result, "GBbD")

    def test_ordering_with_sharps_crossing_octave(self):
        """F#3(54) < A3(57) < C#4(61) — pitch order gives F#AC#."""
        result = pm._render_slot(["F#3", "A3", "C#4"], {}, False)
        self.assertEqual(result, "F#AC#")

    def test_chord_map_still_works_with_pitch_ordering(self):
        """Chord map lookup uses alphabetical key; render still correct."""
        chord_map = {"BDG": "G"}
        # G3(55) < B3(59) < D4(62) → alphabetical key 'BDG' → chord 'G'
        result = pm._render_slot(["B3", "D4", "G3"], chord_map, False)
        self.assertEqual(result, "G")

    def test_chord_map_gbce_example(self):
        """Chord map lookup is pitch-independent (alphabetical key)."""
        chord_map = {"BCEG": "Cmaj7"}
        result = pm._render_slot(["G3", "B3", "C4", "E4"], chord_map, False)
        self.assertEqual(result, "Cmaj7")


class TestParsePitch(unittest.TestCase):
    """_parse_pitch: strip octave and normalise accidentals."""

    def test_natural(self):
        self.assertEqual(pm._parse_pitch("C3"), "C")

    def test_sharp_ascii(self):
        self.assertEqual(pm._parse_pitch("F#3"), "F#")

    def test_sharp_unicode(self):
        self.assertEqual(pm._parse_pitch("F♯3"), "F#")

    def test_flat_ascii(self):
        self.assertEqual(pm._parse_pitch("Bb4"), "A#")  # sharp table by default

    def test_flat_use_flats(self):
        self.assertEqual(pm._parse_pitch("Bb4", use_flats=True), "Bb")

    def test_sharp_as_flat(self):
        # A# is enharmonic to Bb; with use_flats=True the flat table is used
        self.assertEqual(pm._parse_pitch("A#4", use_flats=True), "Bb")

    def test_unicode_flat(self):
        self.assertEqual(pm._parse_pitch("B♭4"), "A#")  # sharp table

    def test_uppercase(self):
        self.assertEqual(pm._parse_pitch("c3"), "C")

    def test_high_octave(self):
        self.assertEqual(pm._parse_pitch("G7"), "G")


class TestPositionToSlot(unittest.TestCase):
    """_position_to_slot: bar/beat/div → (measure, slot)."""

    def test_first_slot(self):
        self.assertEqual(pm._position_to_slot(1, 1, 1), (0, 0))

    def test_second_beat(self):
        self.assertEqual(pm._position_to_slot(1, 2, 1), (0, 4))

    def test_third_beat_second_div(self):
        self.assertEqual(pm._position_to_slot(1, 3, 2), (0, 9))

    def test_second_bar(self):
        self.assertEqual(pm._position_to_slot(2, 1, 1), (1, 0))

    def test_last_slot_of_bar(self):
        # Beat 4, div 4 → slot 15
        self.assertEqual(pm._position_to_slot(1, 4, 4), (0, 15))


class TestParseFile(unittest.TestCase):
    """parse_file: read MIDI text lines into an event map."""

    def _make_file(self, content: str, tmpdir: Path) -> Path:
        p = tmpdir / "test_midi.txt"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_single_note(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "Note\t1 1 1 1\tC3\t100\t0 1 0 0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertIn((0, 0), events)
        self.assertEqual(events[(0, 0)], ["C3"])

    def test_simultaneous_notes(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "Note\t1 1 1 1\tC3\t100\t0 1 0 0\n"
                "Note\t1 1 1 1\tE3\t100\t0 1 0 0\n"
                "Note\t1 1 1 1\tG3\t100\t0 1 0 0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertEqual(sorted(events[(0, 0)]), ["C3", "E3", "G3"])

    def test_different_beats(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "Note\t1 1 1 1\tC3\t100\t0 1 0 0\n"
                "Note\t1 3 1 1\tG3\t85\t0 0 2 0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertIn((0, 0), events)
        self.assertIn((0, 8), events)  # beat 3, div 1 → slot 8

    def test_multiple_measures(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "Note\t1 1 1 1\tC3\t100\t0 1 0 0\n"
                "Note\t2 1 1 1\tD3\t100\t0 1 0 0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertIn((0, 0), events)
        self.assertIn((1, 0), events)

    def test_ignores_non_note_lines(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "# Comment line\n"
                "CC\t1 1 1 1\t64\n"
                "Note\t1 1 1 1\tC3\t100\t0 1 0 0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertEqual(len(events), 1)

    def test_unicode_sharp_in_pitch(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "Note\t1 1 1 1\tF♯3\t100\t0 1 0 0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertIn((0, 0), events)
        self.assertEqual(events[(0, 0)], ["F♯3"])

    # ── Format B (position-first, real Logic Pro Event List) ──────────────

    def test_format_b_single_note(self):
        """Position-first format: <bar> <beat> <div> <tick> Note <ch> <pitch>..."""
        with TemporaryDirectory() as td:
            f = self._make_file(
                "53 1 1 1 \t Note\t 11\t C2\t 79\t 0 1 2 154\n"
                "\t\t\t Vit. rel.\t\t\t 0\t\t\n",
                Path(td),
            )
            events = pm.parse_file(f)
        # Bar 53, beat 1, div 1 → measure 52, slot 0
        self.assertIn((52, 0), events)
        self.assertEqual(events[(52, 0)], ["C2"])

    def test_format_b_simultaneous_notes(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "53 2 1 1  Note  11  C3  85  0 0 1 195\n"
                "53 2 1 1  Note  11  E3  78  0 0 1 140\n",
                Path(td),
            )
            events = pm.parse_file(f)
        # Bar 53, beat 2, div 1 → measure 52, slot 4
        self.assertIn((52, 4), events)
        self.assertEqual(sorted(events[(52, 4)]), ["C3", "E3"])

    def test_format_b_unicode_sharp(self):
        with TemporaryDirectory() as td:
            f = self._make_file(
                "53 4 1 1  Note  11  F♯3  73  0 0 2 18\n",
                Path(td),
            )
            events = pm.parse_file(f)
        # Bar 53, beat 4, div 1 → measure 52, slot 12
        self.assertIn((52, 12), events)
        self.assertEqual(events[(52, 12)], ["F♯3"])

    def test_format_b_ignores_vit_rel_lines(self):
        """Vit. rel. continuation lines must be silently skipped."""
        with TemporaryDirectory() as td:
            f = self._make_file(
                "53 1 1 1  Note  11  C2  79  0 1 2 154\n"
                "   Vit. rel.   0\n"
                "53 1 3 1  Note  11  G2  76  0 0 1 97\n"
                "   Vit. rel.   0\n",
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertEqual(len(events), 2)

    def test_both_formats_in_same_file(self):
        """A file may mix Format A and Format B lines."""
        with TemporaryDirectory() as td:
            f = self._make_file(
                "Note  1 1 1 1  C3  100  0 1 0 0\n"   # Format A
                "2 1 1 1  Note  11  D3  90  0 1 0 0\n",  # Format B
                Path(td),
            )
            events = pm.parse_file(f)
        self.assertIn((0, 0), events)  # bar 1, beat 1 → measure 0, slot 0
        self.assertIn((1, 0), events)  # bar 2, beat 1 → measure 1, slot 0


class TestRenderSlot(unittest.TestCase):
    """_render_slot: convert raw pitches to display token."""

    def test_single_note(self):
        self.assertEqual(pm._render_slot(["C3"], {}, False), "C")

    def test_chord_no_map(self):
        result = pm._render_slot(["C3", "E3", "G3"], {}, False)
        self.assertEqual(result, "CEG")

    def test_chord_with_map(self):
        chord_map = {"CEG": "C"}
        result = pm._render_slot(["C3", "E3", "G3"], chord_map, False)
        self.assertEqual(result, "C")

    def test_flat_rendering(self):
        result = pm._render_slot(["A#3"], {}, use_flats=True)
        self.assertEqual(result, "Bb")

    def test_duplicate_pitches_deduplicated(self):
        # If the same pitch appears twice (velocity layers), show it once
        result = pm._render_slot(["C3", "C3", "G3"], {}, False)
        self.assertEqual(result, "CG")


class TestBuildOutput(unittest.TestCase):
    """build_output: integration test for full pipeline."""

    def _make_events(self):
        """Two bars: bar 1 has C major at slot 0 and G at slot 8;
        bar 2 has D minor at slot 0."""
        events = {
            (0, 0): ["C3", "E3", "G3"],
            (0, 8): ["G3"],
            (1, 0): ["D3", "F3", "A3"],
        }
        return events

    def test_per_measure_no_chord_map(self):
        events = self._make_events()
        result = pm.build_output(events, {}, False, per_measure=True)
        lines = result.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("Bar   1:"))
        self.assertTrue(lines[1].startswith("Bar   2:"))

    def test_per_measure_with_chord_map(self):
        events = self._make_events()
        chord_map = {"CEG": "C", "ADF": "Dm"}
        result = pm.build_output(events, chord_map, False, per_measure=True)
        lines = result.splitlines()
        # Bar 1 should show 'C' (chord name) not 'CEG'
        self.assertIn("C", lines[0])
        # Bar 2 should show 'Dm' (chord name)
        self.assertIn("Dm", lines[1])

    def test_continuous_mode(self):
        events = self._make_events()
        result = pm.build_output(events, {}, False, per_measure=False)
        # Should be a single line with '|' separator between bars
        self.assertNotIn("\n", result.strip())
        self.assertIn("|", result)

    def test_empty_events(self):
        result = pm.build_output({}, {}, False, per_measure=True)
        self.assertEqual(result, "")

    def test_slot_spacing(self):
        """Notes at slot 0 and slot 8 should have 7 spaces between them."""
        events = {(0, 0): ["C3"], (0, 8): ["G3"]}
        result = pm.build_output(events, {}, False, per_measure=True)
        # Strip the "Bar   1: " prefix
        bar_content = result.split(": ", 1)[1]
        # C, 7 spaces, G
        self.assertEqual(bar_content, "C       G")

    def test_gbce_in_output(self):
        """G3 B3 C4 E4 in same slot → output 'GBCE' in pitch order."""
        events = {(0, 0): ["G3", "B3", "C4", "E4"]}
        result = pm.build_output(events, {}, False, per_measure=True)
        bar_content = result.split(": ", 1)[1]
        self.assertEqual(bar_content, "GBCE")


class TestLoadChordMap(unittest.TestCase):
    """load_chord_map: JSON file loading."""

    def test_loads_valid_file(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "chords.json"
            p.write_text(json.dumps({"CEG": "C", "ADF": "Dm"}), encoding="utf-8")
            result = pm.load_chord_map(p)
        self.assertEqual(result, {"CEG": "C", "ADF": "Dm"})

    def test_returns_empty_for_missing_file(self):
        result = pm.load_chord_map(Path("/nonexistent/path.json"))
        self.assertEqual(result, {})

    def test_returns_empty_for_none(self):
        result = pm.load_chord_map(None)
        self.assertEqual(result, {})


class TestCLI(unittest.TestCase):
    """main(): end-to-end CLI integration test."""

    SAMPLE_MIDI = textwrap.dedent("""\
        Note\t1 1 1 1\tC3\t100\t0 1 0 0
        Note\t1 1 1 1\tE3\t100\t0 1 0 0
        Note\t1 1 1 1\tG3\t100\t0 1 0 0
        Note\t1 3 1 1\tG3\t85\t0 0 2 0
        Note\t2 1 1 1\tD3\t100\t0 1 0 0
        Note\t2 1 1 1\tF3\t100\t0 1 0 0
        Note\t2 1 1 1\tA3\t100\t0 1 0 0
    """)

    def test_per_measure_output(self):
        with TemporaryDirectory() as td:
            midi = Path(td) / "midi.txt"
            midi.write_text(self.SAMPLE_MIDI, encoding="utf-8")
            out = Path(td) / "out.txt"
            rc = pm.main([str(midi), "--output", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
        self.assertIn("Bar", text)

    def test_continuous_output(self):
        with TemporaryDirectory() as td:
            midi = Path(td) / "midi.txt"
            midi.write_text(self.SAMPLE_MIDI, encoding="utf-8")
            out = Path(td) / "out.txt"
            rc = pm.main([str(midi), "--continuous", "--output", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8").strip()
        self.assertIn("|", text)
        self.assertEqual(len(text.splitlines()), 1)

    def test_missing_input_returns_error(self):
        rc = pm.main(["/nonexistent/file.txt"])
        self.assertEqual(rc, 1)

    def test_chord_map_applied(self):
        with TemporaryDirectory() as td:
            midi = Path(td) / "midi.txt"
            midi.write_text(self.SAMPLE_MIDI, encoding="utf-8")
            cmap = Path(td) / "chords.json"
            cmap.write_text(json.dumps({"CEG": "C", "ADF": "Dm"}), encoding="utf-8")
            out = Path(td) / "out.txt"
            pm.main([str(midi), "--chord-map", str(cmap), "--output", str(out)])
            text = out.read_text(encoding="utf-8")
        # Bar 1 should label the C major chord as 'C'
        bar1_line = [l for l in text.splitlines() if "Bar   1:" in l][0]
        self.assertIn("C", bar1_line)
        # Bar 2 should label the D minor chord as 'Dm'
        bar2_line = [l for l in text.splitlines() if "Bar   2:" in l][0]
        self.assertIn("Dm", bar2_line)

    def test_sample_file_gbce_pitch_order(self):
        """End-to-end: bar 4 of sample file has G3 B3 D4 → must be 'GBD'.

        Uses an empty chord map so that the raw note names are rendered
        (not replaced by a chord label from the default chord_map.json).
        """
        sample = Path(__file__).parent / "sample_midi_info_notes.txt"
        if not sample.exists():
            self.skipTest("sample_midi_info_notes.txt not found")
        with TemporaryDirectory() as td:
            empty_cmap = Path(td) / "empty.json"
            empty_cmap.write_text("{}", encoding="utf-8")
            out = Path(td) / "out.txt"
            rc = pm.main([str(sample), "--chord-map", str(empty_cmap), "--output", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
        bar4_line = [l for l in text.splitlines() if "Bar   4:" in l][0]
        bar4_content = bar4_line.split(": ", 1)[1]
        # G3(55) < B3(59) < D4(62): pitch order is GBD, not alphabetical BDG
        self.assertTrue(
            bar4_content.startswith("GBD"),
            f"Expected 'GBD...' but got: {bar4_content!r}",
        )


if __name__ == "__main__":
    unittest.main()
