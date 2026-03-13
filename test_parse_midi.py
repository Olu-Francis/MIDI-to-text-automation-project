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


if __name__ == "__main__":
    unittest.main()
