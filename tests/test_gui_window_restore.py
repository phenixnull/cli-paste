import types
import unittest

import gui


class FakeWindow:
    def __init__(self, state="iconic"):
        self._state = state
        self.calls = []

    def state(self, value=None):
        if value is None:
            return self._state
        self.calls.append(("state", value))
        self._state = value

    def deiconify(self):
        self.calls.append("deiconify")
        self._state = "normal"

    def lift(self):
        self.calls.append("lift")

    def attributes(self, name, value):
        self.calls.append(("attributes", name, value))

    def focus_force(self):
        self.calls.append("focus_force")

    def after_idle(self, callback):
        self.calls.append("after_idle")
        callback()


class RestoreWindowTests(unittest.TestCase):
    def test_restore_window_brings_window_to_front(self):
        window = FakeWindow(state="iconic")

        gui._restore_window(window)

        self.assertIn("deiconify", window.calls)
        self.assertIn(("state", "normal"), window.calls)
        self.assertIn("lift", window.calls)
        self.assertIn("focus_force", window.calls)
        self.assertEqual(
            [
                ("attributes", "-topmost", True),
                ("attributes", "-topmost", False),
            ],
            [call for call in window.calls if isinstance(call, tuple) and call[0] == "attributes"],
        )

    def test_on_root_mapped_restores_only_main_window(self):
        root = FakeWindow(state="normal")
        app = gui.App.__new__(gui.App)
        app.root = root

        app._on_root_mapped(types.SimpleNamespace(widget=root))

        self.assertIn("after_idle", root.calls)
        self.assertIn("lift", root.calls)

    def test_on_root_mapped_ignores_child_widgets(self):
        root = FakeWindow(state="normal")
        child = object()
        app = gui.App.__new__(gui.App)
        app.root = root

        app._on_root_mapped(types.SimpleNamespace(widget=child))

        self.assertEqual([], root.calls)


if __name__ == "__main__":
    unittest.main()
