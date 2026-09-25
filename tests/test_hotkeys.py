from dataclasses import dataclass
import unittest

from hotkeys import HotkeyState


class HotkeyTests(unittest.TestCase):
    def tracker(self):
        changes, cleared = [], []
        state = HotkeyState(
            {"ctrl", "r"}, lambda key: "ctrl" if key in ("left", "right") else key,
            changes.append, lambda: cleared.append(True),
        )
        return state, changes, cleared

    def test_repeat_and_unrelated_release_do_not_toggle_recording(self):
        state, changes, cleared = self.tracker()
        for key in ("left", "r", "r", "r", "x"):
            state.press(key)
        state.release("x")
        self.assertEqual(changes, [True])
        state.release("r")
        self.assertEqual(changes, [True, False])
        self.assertEqual(cleared, [])
        state.release("left")
        self.assertEqual(cleared, [True])

    def test_releasing_one_of_two_modifiers_keeps_chord_active(self):
        state, changes, _ = self.tracker()
        for key in ("left", "right", "r"):
            state.press(key)
        state.release("left")
        self.assertEqual(changes, [True])
        state.release("right")
        self.assertEqual(changes, [True, False])

    def test_release_before_activation_does_not_start_or_stop(self):
        state, changes, cleared = self.tracker()
        state.press("left")
        state.release("left")
        self.assertEqual(changes, [])
        self.assertEqual(cleared, [])

    def test_character_case_change_on_release_does_not_stick(self):
        @dataclass(frozen=True)
        class Key:
            char: str

        changes, cleared = [], []
        state = HotkeyState(
            {"r"}, lambda key: key.char.lower(), changes.append, lambda: cleared.append(True)
        )
        state.press(Key("R"))
        state.release(Key("r"))
        self.assertEqual(changes, [True, False])
        self.assertEqual(cleared, [True])


if __name__ == "__main__":
    unittest.main()
