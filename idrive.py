# bmw idrive touch controller on a mac through a candlelight adapter
# prints the raw can frames with what they mean, --mac controls the mac too

import argparse
import time

from candlelight import CanAdapter
from touchpad import Touchpad

# the controller says nothing until it thinks the car is on, so we fake it
KEEP_ALIVE = [
    (0x12F, [0x12, 0x34, 0x8A, 0xDD, 0xF1, 0x15, 0x30, 0x02], 0.1),
    (0x202, [0xFD, 0xFF], 0.2),
    (0x510, [0x40, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], 0.5),
]

# head unit asking if a controller is there
HELLO = 0x273
HELLO_MSG = [0x1D, 0xE1, 0x00, 0xF0, 0xFF, 0x7F, 0xDE]

TOUCH, KNOB, BUTTONS, HELLO_BACK = 0x0BF, 0x264, 0x267, 0x277

BUTTON_NAMES = {
    (0xC0, 0x01): "menu", (0xC0, 0x02): "back", (0xC0, 0x04): "option",
    (0xC0, 0x08): "radio", (0xC0, 0x10): "media", (0xC0, 0x20): "nav",
    (0xC0, 0x40): "tel", (0xDE, 0x01): "knob",
}
# pushing the knob sideways
TILT = 0xDD
TILTS = {0x1: "up", 0x2: "right", 0x4: "down", 0x8: "left"}

MOUSE_SPEED = 1.2
SCROLL_SPEED = 1.5

# seconds of silence before the controller counts as gone
QUIET_AFTER = 2.0


class Controller:
    def __init__(self, mac=None):
        self.mac = mac
        self.mouse = mac.Mouse() if mac else None
        self.pad = Touchpad()
        self.held = set()
        self.knob = None
        self.leftover = [0.0, 0.0]
        self.hold_still_until = 0

    def handle(self, can_id, data):
        # acts on a frame and returns a short label for it
        if can_id == TOUCH and len(data) >= 8:
            return self.touch(data)
        if can_id == KNOB and len(data) >= 5:
            return self.roll(data[3] | data[4] << 8)
        if can_id == BUTTONS and len(data) >= 6:
            return self.button(data[3], data[4], data[5])
        if can_id == HELLO_BACK:
            # answering hello also resets the knob count to 0x8000, without this
            # the jump back looks like a turn the other way
            self.knob = 0x8000
            return "hello back"
        return ""

    # buttons

    def button(self, state, group, code):
        if group == TILT:
            names = [n for bit, n in TILTS.items() if state >> 4 & bit]
            if state == 0:
                names = [n for n in TILTS.values() if "tilt " + n in self.held]
            names = ["tilt " + n for n in names]
        else:
            name = BUTTON_NAMES.get((group, code))
            if not name:
                return "unknown button" if code else ""
            names = [name]

        labels = []
        for name in names:
            pressed = state != 0
            if pressed == (name in self.held):
                continue
            if pressed:
                self.held.add(name)
            else:
                self.held.discard(name)
            what = self.do_button(name) if pressed and self.mouse else ""
            labels.append(f"{name} {'pressed' if pressed else 'released'}" + (f"  {what}" if what else ""))
        return "  ".join(labels)

    def do_button(self, name):
        mac, mouse = self.mac, self.mouse
        if name == "menu":
            mac.mission_control()
            return "mission control"
        if name == "knob":
            mac.media_key(mac.PLAY)
            # pushing the knob wiggles your finger, ignore it for a moment
            self.hold_still_until = time.monotonic() + 0.3
            return "play pause"
        if name == "tilt right":
            mac.media_key(mac.NEXT)
            return "next song"
        if name == "tilt left":
            mac.media_key(mac.PREVIOUS)
            return "previous song"
        if name == "tilt up":
            mac.open_app("Siri")
            return "siri"
        if name == "tilt down":
            mouse.spotlight()
            return "spotlight"
        if name == "media":
            mac.open_app("Music")
            return "open music"
        if name == "radio":
            mac.open_url("music://music.apple.com/library/playlists")
            return "open playlists"
        if name == "nav":
            mac.open_app("Maps")
            return "open maps"
        if name == "tel":
            mac.open_app("Messages")
            return "open messages"
        if name == "option":
            mouse.right_click()
            return "right click"
        if name == "back":
            mouse.switch_app()
            return "switch app"
        return ""

    # knob

    def roll(self, position):
        # 16 bit position that wraps around
        last, self.knob = self.knob, position
        if last is None:
            return ""
        steps = (position - last + 0x8000) % 0x10000 - 0x8000
        if not steps:
            return ""
        way = "right" if steps > 0 else "left"
        if not self.mouse:
            return f"roll {way}"
        for _ in range(abs(steps)):
            self.mac.media_key(self.mac.VOLUME_UP if steps > 0 else self.mac.VOLUME_DOWN)
        return f"roll {way}  volume {'up' if steps > 0 else 'down'}"

    # touchpad

    def touch(self, data):
        label = ""
        for kind, *values in self.pad.update(data):
            label = self.gesture(kind, values) or label
        if not label:
            n = len(self.pad.fingers)
            label = "lift" if n == 0 else "touch" if n == 1 else "two fingers"
        return label

    def gesture(self, kind, values):
        mouse = self.mouse

        if kind == "fingers" and values[0] and mouse:
            # touching the pad stops a glide like a real trackpad
            mouse.stop_glide()
        elif kind == "move" and mouse and time.monotonic() > self.hold_still_until:
            dx, dy = values
            # a bit of acceleration so slow moves stay precise
            gain = MOUSE_SPEED * (1 + 0.05 * (dx * dx + dy * dy) ** 0.5)
            self.leftover[0] += dx * gain
            self.leftover[1] += dy * gain
            mx, my = int(self.leftover[0]), int(self.leftover[1])
            self.leftover[0] -= mx
            self.leftover[1] -= my
            if mx or my:
                mouse.move(mx, my)
        elif kind == "scroll":
            if mouse:
                mouse.swipe_scroll(values[0] * SCROLL_SPEED, values[1] * SCROLL_SPEED)
            return "scroll"
        elif kind == "scroll_end" and mouse:
            mouse.swipe_scroll_end()
        elif kind == "tap":
            if mouse:
                mouse.click()
            return "tap"
        elif kind == "two_finger_tap":
            if mouse:
                mouse.right_click()
            return "two finger tap"
        elif kind == "drag_start":
            if mouse:
                mouse.press()
            return "drag"
        elif kind == "drag_end":
            if mouse:
                mouse.let_go()
            return "drop"
        elif kind == "zoom_start":
            if mouse:
                mouse.zoom_start()
            return "pinch out" if values[0] > 0 else "pinch in"
        elif kind == "zoom":
            if mouse:
                mouse.zoom_by(values[0])
            return "pinch"
        elif kind == "zoom_end" and mouse:
            mouse.zoom_end()
        elif kind == "swipe":
            if mouse:
                mouse.swipe_page(values[0])
            return "swipe back" if values[0] > 0 else "swipe forward"
        return ""


def main():
    parser = argparse.ArgumentParser(description="bmw idrive touch controller on a mac")
    parser.add_argument("--mac", action="store_true", help="control the mac with it")
    args = parser.parse_args()

    mac = None
    if args.mac:
        import mac
        if not mac.ask_permission():
            print("clicks and keys need accessibility access for this terminal, quit and reopen it after allowing")

    can = CanAdapter(500_000)
    controller = Controller(mac)
    status = None
    last_heard = 0.0
    next_send = {}
    count = 0

    def say(new):
        nonlocal status
        if status != new:
            status = new
            print(new, flush=True)

    try:
        while True:
            if not can.connected:
                say("waiting for adapter")
                if not can.open():
                    time.sleep(0.5)
                    continue
                say("adapter connected, waking controller")

            now = time.monotonic()
            for can_id, data, every in KEEP_ALIVE:
                if now >= next_send.get(can_id, 0):
                    can.send(can_id, data)
                    next_send[can_id] = now + every
            if now >= next_send.get(HELLO, 0):
                can.send(HELLO, HELLO_MSG + [count])
                count = (count + 1) % 256
                next_send[HELLO] = now + 1.0

            while frame := can.recv():
                can_id, data = frame
                last_heard = time.monotonic()
                say("controller connected")
                label = controller.handle(can_id, data)
                print(f"{can_id:03X}  {data.hex(' ').upper():<23}  {label}", flush=True)

            if status == "controller connected" and time.monotonic() - last_heard > QUIET_AFTER:
                say("controller lost, check power and can wires")

            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        if controller.mouse:
            controller.mouse.let_go()
        can.close()
        print("\nbye")


if __name__ == "__main__":
    main()
