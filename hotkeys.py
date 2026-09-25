"""Hotkey edge detection independent of the native keyboard backend."""


class HotkeyState:
    def __init__(self, keys, canonical, on_change, on_clear):
        self.keys = set(keys)
        self.canonical = canonical
        self.on_change = on_change
        self.on_clear = on_clear
        self.pressed = {}
        self.active = False
        self.triggered = False

    def press(self, key):
        # Track physical keys separately: releasing left Shift must not forget a
        # right Shift which is still held. Repeated key-down events are harmless.
        canonical = self.canonical(key)
        identity = canonical if getattr(key, "char", None) is not None else key
        self.pressed[identity] = canonical
        self._update()

    def release(self, key):
        identity = self.canonical(key) if getattr(key, "char", None) is not None else key
        self.pressed.pop(identity, None)
        self._update()

    def _update(self):
        down = set(self.pressed.values())
        active = self.keys.issubset(down)
        if active != self.active:
            self.active = active
            self.triggered |= active
            self.on_change(active)
        if self.triggered and not (down & self.keys):
            self.triggered = False
            self.on_clear()
