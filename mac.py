# everything that talks to macos, coregraphics through ctypes so nothing to install
# clicks and keys need the terminal allowed in Accessibility (Device Control on newer macos)

import ctypes
import subprocess
import threading
import time
from collections import deque
from ctypes import c_bool, c_double, c_int16, c_int32, c_int64, c_uint16, c_uint32, c_uint64, c_void_p

cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
ax = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")


class Point(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class Rect(ctypes.Structure):
    _fields_ = [("origin", Point), ("size", Point)]


def fn(lib, name, returns, *args):
    f = getattr(lib, name)
    f.restype, f.argtypes = returns, list(args)
    return f


new_event = fn(cg, "CGEventCreate", c_void_p, c_void_p)
event_location = fn(cg, "CGEventGetLocation", Point, c_void_p)
mouse_event = fn(cg, "CGEventCreateMouseEvent", c_void_p, c_void_p, c_uint32, Point, c_uint32)
scroll_event = fn(cg, "CGEventCreateScrollWheelEvent2", c_void_p, c_void_p, c_uint32, c_uint32, c_int32, c_int32, c_int32)
key_event = fn(cg, "CGEventCreateKeyboardEvent", c_void_p, c_void_p, c_uint16, c_bool)
set_type = fn(cg, "CGEventSetType", None, c_void_p, c_uint32)
set_flags = fn(cg, "CGEventSetFlags", None, c_void_p, c_uint64)
set_int = fn(cg, "CGEventSetIntegerValueField", None, c_void_p, c_uint32, c_int64)
set_double = fn(cg, "CGEventSetDoubleValueField", None, c_void_p, c_uint32, c_double)
post = fn(cg, "CGEventPost", None, c_uint32, c_void_p)
display_list = fn(cg, "CGGetActiveDisplayList", c_int32, c_uint32, ctypes.POINTER(c_uint32), ctypes.POINTER(c_uint32))
display_bounds = fn(cg, "CGDisplayBounds", Rect, c_uint32)
warp = fn(cg, "CGWarpMouseCursorPosition", c_int32, Point)
release = fn(cf, "CFRelease", None, c_void_p)
is_trusted = fn(ax, "AXIsProcessTrusted", c_bool)

MOVE, LEFT_DOWN, LEFT_UP, RIGHT_DOWN, RIGHT_UP, DRAG = 5, 1, 2, 3, 4, 6
CLICK_COUNT = 1
CMD, CTRL = 0x100000, 0x40000
MODIFIER_KEYS = {CMD: 0x37, CTRL: 0x3B}
TAB, LEFT_BRACKET, RIGHT_BRACKET, SPACE = 0x30, 0x21, 0x1E, 0x31

# real trackpad gesture numbers, not in apples headers
GESTURE = 29
GESTURE_KIND, GESTURE_PHASE, ZOOM_AMOUNT, SWIPE_WAY = 110, 132, 113, 115
ZOOM, PAGE_SWIPE = 8, 16
SWIPE_LEFT, SWIPE_RIGHT = 4, 8
BEGAN, CHANGED, ENDED = 1, 2, 4

# trackpad style scrolling with a glide after you let go
CONTINUOUS, SCROLL_PHASE, GLIDE_PHASE = 88, 99, 123
FRICTION = 0.94

# media keys from the top row of a mac keyboard
VOLUME_UP, VOLUME_DOWN, MUTE, PLAY, NEXT, PREVIOUS = 0, 1, 7, 16, 17, 18


def allowed():
    return bool(is_trusted())


def ask_permission():
    # shows the macos allow box if we dont have access yet
    ask = fn(ax, "AXIsProcessTrustedWithOptions", c_bool, c_void_p)
    make = fn(cf, "CFDictionaryCreate", c_void_p, c_void_p, ctypes.POINTER(c_void_p),
              ctypes.POINTER(c_void_p), ctypes.c_long, c_void_p, c_void_p)
    keys = (c_void_p * 1)(c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt"))
    values = (c_void_p * 1)(c_void_p.in_dll(cf, "kCFBooleanTrue"))
    options = make(None, keys, values, 1,
                   ctypes.addressof(c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
                   ctypes.addressof(c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
    ok = ask(options)
    release(options)
    return bool(ok)


def send(event, clean=True):
    # after a cmd shortcut macos can think cmd is still held and every click
    # opens a new tab, so clear modifiers
    if clean:
        set_flags(event, 0)
    post(0, event)
    release(event)


def where():
    e = new_event(None)
    p = event_location(e)
    release(e)
    return p.x, p.y


def screen_edges():
    ids, n = (c_uint32 * 16)(), c_uint32()
    display_list(16, ids, ctypes.byref(n))
    screens = [display_bounds(ids[i]) for i in range(n.value)]
    return (min(s.origin.x for s in screens), min(s.origin.y for s in screens),
            max(s.origin.x + s.size.x for s in screens) - 1, max(s.origin.y + s.size.y for s in screens) - 1)


def media_key(key):
    # coregraphics cant make media key events so we ask appkit through objc
    msg = ctypes.cast(objc.objc_msgSend, c_void_p).value
    get_class = fn(objc, "objc_getClass", c_void_p, ctypes.c_char_p)
    selector = fn(objc, "sel_registerName", c_void_p, ctypes.c_char_p)
    pool_push = fn(objc, "objc_autoreleasePoolPush", c_void_p)
    pool_pop = fn(objc, "objc_autoreleasePoolPop", None, c_void_p)
    make = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_uint64, Point, c_uint64, c_double,
                            c_int64, c_void_p, c_int16, c_int64, c_int64)(msg)
    to_cg = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p)(msg)

    pool = pool_push()
    # down then up
    for state in (0xA, 0xB):
        e = make(get_class(b"NSEvent"), selector(b"otherEventWithType:location:modifierFlags:timestamp:"
                                                  b"windowNumber:context:subtype:data1:data2:"),
                 14, Point(0, 0), state << 8, 0, 0, None, 8, key << 16 | state << 8, -1)
        post(0, to_cg(e, selector(b"CGEvent")))
    pool_pop(pool)


def open_app(name):
    subprocess.Popen(["open", "-a", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url):
    subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def mission_control():
    path = "/System/Applications/Mission Control.app/Contents/MacOS/Mission Control"
    subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Mouse:
    def __init__(self):
        self.edges = screen_edges()
        self.can_post = allowed()
        self.holding = False
        self.last_click = (0, 0, 0)
        self.clicks = 0
        self.scrolling = False
        self.recent = deque(maxlen=8)
        self.leftover = [0.0, 0.0]
        self.glide_id = 0

    # pointer and buttons

    def move(self, dx, dy):
        x, y = where()
        left, top, right, bottom = self.edges
        to = Point(min(max(x + dx, left), right), min(max(y + dy, top), bottom))
        # warp works without accessibility, the real event is for hover and drag
        warp(to)
        if self.can_post:
            send(mouse_event(None, DRAG if self.holding else MOVE, to, 0))

    def press(self):
        # a quick second click in the same spot is a double click
        now, (x, y) = time.monotonic(), where()
        t, lx, ly = self.last_click
        self.clicks = self.clicks + 1 if now - t < 0.45 and abs(x - lx) < 12 and abs(y - ly) < 12 else 1
        self.last_click = (now, x, y)
        self.holding = True
        self.button(LEFT_DOWN, 0)

    def let_go(self):
        if self.holding:
            self.holding = False
            self.button(LEFT_UP, 0)

    def click(self):
        self.press()
        self.let_go()

    def right_click(self):
        self.button(RIGHT_DOWN, 1)
        self.button(RIGHT_UP, 1)

    def button(self, kind, which):
        x, y = where()
        e = mouse_event(None, kind, Point(x, y), which)
        set_int(e, CLICK_COUNT, self.clicks if which == 0 else 1)
        send(e)

    # keyboard

    def key(self, code, mods=0):
        # press modifiers for real so macos never thinks one is still held
        held = [m for m in MODIFIER_KEYS if mods & m]
        flags = 0
        for m in held:
            flags |= m
            self.tap(MODIFIER_KEYS[m], True, flags)
        self.tap(code, True, flags)
        self.tap(code, False, flags)
        for m in reversed(held):
            flags &= ~m
            self.tap(MODIFIER_KEYS[m], False, flags)

    def tap(self, code, down, flags):
        e = key_event(None, code, down)
        set_flags(e, flags)
        send(e, clean=False)

    def back(self):
        self.key(LEFT_BRACKET, CMD)

    def forward(self):
        self.key(RIGHT_BRACKET, CMD)

    def switch_app(self):
        self.key(TAB, CMD)

    def spotlight(self):
        self.key(SPACE, CMD)

    # scrolling

    def scroll(self, dx=0, dy=0, lines=False):
        send(scroll_event(None, 1 if lines else 0, 2, int(dy), int(dx), 0))

    def swipe_scroll(self, dx, dy):
        self.stop_glide()
        self.recent.append((time.monotonic(), dx, dy))
        self.scroll_px(dx, dy, phase=CHANGED if self.scrolling else BEGAN)
        self.scrolling = True

    def swipe_scroll_end(self):
        if not self.scrolling:
            return
        self.scrolling = False
        self.scroll_px(0, 0, phase=ENDED)
        # keep going at the speed the fingers lifted at
        now = time.monotonic()
        moves = [m for m in self.recent if now - m[0] < 0.1]
        self.recent.clear()
        if len(moves) < 2:
            return
        span = max(now - moves[0][0], 0.016)
        vx = sum(m[1] for m in moves) / span
        vy = sum(m[2] for m in moves) / span
        threading.Thread(target=self.glide, args=(vx, vy, self.glide_id), daemon=True).start()

    def stop_glide(self):
        self.glide_id += 1

    def glide(self, vx, vy, me):
        phase = 1
        while me == self.glide_id and (vx * vx + vy * vy) ** 0.5 > 30:
            self.scroll_px(vx * 0.016, vy * 0.016, glide=phase)
            phase = 2
            vx *= FRICTION
            vy *= FRICTION
            time.sleep(0.016)
        if phase == 2:
            self.scroll_px(0, 0, glide=3)

    def scroll_px(self, dx, dy, phase=0, glide=0):
        self.leftover[0] += dx
        self.leftover[1] += dy
        px, py = round(self.leftover[0]), round(self.leftover[1])
        self.leftover[0] -= px
        self.leftover[1] -= py
        e = scroll_event(None, 0, 2, py, px, 0)
        set_int(e, CONTINUOUS, 1)
        set_int(e, SCROLL_PHASE, phase)
        set_int(e, GLIDE_PHASE, glide)
        send(e)

    # pinch and page swipes

    def zoom_start(self):
        self.stop_glide()
        self.gesture(ZOOM, BEGAN)

    def zoom_by(self, amount):
        self.gesture(ZOOM, CHANGED, zoom=amount)

    def zoom_end(self):
        self.gesture(ZOOM, ENDED)

    def swipe_page(self, way):
        # fingers going right means back like a real trackpad
        self.gesture(PAGE_SWIPE, BEGAN, swipe=SWIPE_LEFT if way > 0 else SWIPE_RIGHT)
        self.gesture(PAGE_SWIPE, ENDED)

    def gesture(self, kind, phase, zoom=0.0, swipe=0):
        e = new_event(None)
        set_type(e, GESTURE)
        set_int(e, GESTURE_KIND, kind)
        set_int(e, GESTURE_PHASE, phase)
        if zoom:
            set_double(e, ZOOM_AMOUNT, zoom)
        if swipe:
            set_int(e, SWIPE_WAY, swipe)
        send(e)
