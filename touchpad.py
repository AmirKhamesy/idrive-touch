# turns touchpad frames into gestures
#
# 0x0BF  byte 0     counter
#        byte 1-3   finger 1, 12 bit x and y packed together
#        byte 4     low half finger 1, high half finger 2. 0 touching, 1 not, F just landed
#        byte 5-7   finger 2
#
#   20 00 00 00 11 00 00 00   nobody touching
#   2C 32 70 13 10 00 00 00   one finger
#   24 92 50 06 00 C9 B1 0E   two fingers
#
# y grows towards the top of the pad so it gets flipped for the screen

import time

# a resting finger wobbles a bit, so it has to move SLOP before the cursor
# follows and anything under ROPE gets ignored after that
SLOP = 8
ROPE = 3
SMOOTH = 0.5

TAP_TIME = 0.3
# touch again this soon after a tap and move to drag
TAP_AGAIN = 0.35

# how far two fingers travel before each gesture counts
SCROLL_START = 20
PINCH_START = 50
SWIPE = 60
# a full pinch on my pad is about 350, that doubles the size
ZOOM_SCALE = 1 / 350

# bigger than this in one frame is a glitch
JUMP = 100


def position(lo, mid, hi):
    x = lo | (mid & 0x0F) << 8
    y = mid >> 4 | hi << 4
    return x, y


def parse(data):
    state = data[4]
    fingers = []
    # it sends empty frames at startup, a finger at exactly 0 0 isnt real
    if state & 0x0F != 1 and any(data[1:4]):
        fingers.append(position(data[1], data[2], data[3]))
    if state >> 4 == 0 and any(data[5:8]):
        fingers.append(position(data[5], data[6], data[7]))
    landed = state & 0x0F == 0xF
    return fingers, landed


class Touchpad:
    def __init__(self):
        self.fingers = []
        self.started = 0
        self.most = 0
        self.last_tap = 0
        self.tapped_again = False
        self.dragging = False
        self.moved = False
        self.reset_finger(None)
        self.reset_two()

    def update(self, data):
        # one 0x0BF frame in, list of gestures out
        now_fingers, landed = parse(data)
        before, self.fingers = self.fingers, now_fingers

        if len(now_fingers) != len(before):
            return self.fingers_changed(before, now_fingers)

        if not now_fingers:
            return []
        if landed or any(abs(x - bx) > JUMP or abs(y - by) > JUMP for (x, y), (bx, by) in zip(now_fingers, before)):
            if len(now_fingers) == 1:
                # jumped, start fresh from here
                self.reset_finger(now_fingers[0])
            return []

        if len(now_fingers) == 1:
            return self.follow(now_fingers[0])
        return self.two_fingers(now_fingers, before)

    # one finger

    def reset_finger(self, pos):
        self.smooth = self.anchor = self.landed_at = pos
        self.following = False

    def follow(self, pos):
        # smooth out the noise
        sx, sy = self.smooth
        sx += (pos[0] - sx) * SMOOTH
        sy += (pos[1] - sy) * SMOOTH
        self.smooth = (sx, sy)

        # dont move until the finger really goes somewhere so taps dont nudge the cursor
        if not self.following:
            lx, ly = self.landed_at
            if ((sx - lx) ** 2 + (sy - ly) ** 2) ** 0.5 < SLOP:
                return []
            self.following = self.moved = True

        # the cursor only gets pulled once the finger is more than ROPE away,
        # like dragging something on a short string
        ax, ay = self.anchor
        dx, dy = sx - ax, sy - ay
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= ROPE:
            return []
        pull = (dist - ROPE) / dist
        dx, dy = dx * pull, dy * pull
        self.anchor = (ax + dx, ay + dy)

        out = []
        if self.tapped_again and not self.dragging:
            self.dragging = True
            out.append(("drag_start",))
        out.append(("move", dx, -dy))
        return out

    # touch start and end

    def fingers_changed(self, before, now_fingers):
        now = time.monotonic()
        out = []
        if self.mode == "scroll":
            out.append(("scroll_end",))
        elif self.mode == "pinch":
            out.append(("zoom_end",))
        out.append(("fingers", len(now_fingers)))
        self.reset_two()
        self.reset_finger(now_fingers[0] if len(now_fingers) == 1 else None)

        # new touch
        if not before:
            self.started, self.most, self.moved = now, 0, False
            self.tapped_again = now - self.last_tap < TAP_AGAIN
        self.most = max(self.most, len(now_fingers))

        # all lifted
        if not now_fingers:
            quick = now - self.started < TAP_TIME + 0.1 * (self.most - 1)
            if self.dragging:
                out.append(("drag_end",))
            elif quick and not self.moved:
                if self.most == 1:
                    out.append(("tap",))
                    self.last_tap = now
                else:
                    out.append(("two_finger_tap",))
            self.dragging = self.tapped_again = False
        return out

    # two fingers

    def reset_two(self):
        self.mode = None
        self.spread = self.slide_x = self.slide_y = 0
        # the first position after a finger lands is junk, it made pinches look like scrolls
        self.settle = 1

    def two_fingers(self, now_fingers, before):
        if self.settle:
            self.settle -= 1
            return []

        spread_change = distance(now_fingers) - distance(before)
        (x1, y1), (x2, y2) = now_fingers
        (bx1, by1), (bx2, by2) = before
        dx = ((x1 - bx1) + (x2 - bx2)) / 2
        dy = ((by1 - y1) + (by2 - y2)) / 2
        self.spread += spread_change
        self.slide_x += dx
        self.slide_y += dy
        spread, sx, sy = abs(self.spread), abs(self.slide_x), abs(self.slide_y)

        # keep watching until one gesture clearly wins
        if self.mode is None:
            if spread >= PINCH_START and spread > 1.5 * (sx * sx + sy * sy) ** 0.5:
                self.mode = "pinch"
                self.moved = True
                return [("zoom_start", 1 if self.spread > 0 else -1), ("zoom", self.spread * ZOOM_SCALE)]
            if sx >= SWIPE and sx > 1.5 * sy and sx > spread:
                # one page per swipe
                self.mode = "swiped"
                self.moved = True
                return [("swipe", 1 if self.slide_x > 0 else -1)]
            if sy >= SCROLL_START and sy > sx and sy > spread:
                self.mode = "scroll"
                self.moved = True
            if self.mode is None:
                return []

        if self.mode == "scroll":
            return [("scroll", dx, dy)]

        if self.mode == "pinch" and spread_change:
            return [("zoom", spread_change * ZOOM_SCALE)]
        return []


def distance(fingers):
    (x1, y1), (x2, y2) = fingers
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
