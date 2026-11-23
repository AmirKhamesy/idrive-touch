# small driver for candlelight (gs_usb) adapters
# not using python-can on purpose, on macos its gs_usb backend resets the usb device
# and my adapter disappears until I replug it. this talks to it directly and never resets it

import os
import struct

# pyusb needs libusb, homebrew puts it where macos doesnt look
for path in ("/opt/homebrew/lib", "/usr/local/lib"):
    if os.path.isdir(path):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = path + ":" + os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")

import usb.core
import usb.util

ADAPTERS = {(0x1D50, 0x606F), (0x1209, 0x2323), (0x1CD2, 0x606F), (0x16D0, 0x10B8)}

EP_OUT, EP_IN = 0x02, 0x81
# echo id the adapter puts on frames that came from the bus
FROM_BUS = 0xFFFFFFFF
ERROR_FRAME = 0x20000000


class CanAdapter:
    def __init__(self, bitrate=500_000):
        self.bitrate = bitrate
        self.dev = None
        self.stuck = 0

    @property
    def connected(self):
        return self.dev is not None

    def open(self):
        dev = usb.core.find(custom_match=lambda d: (d.idVendor, d.idProduct) in ADAPTERS)
        if dev is None:
            return False
        try:
            usb.util.claim_interface(dev, 0)

            # ask for its clock so we can work out the bit timing
            caps = bytes(dev.ctrl_transfer(0xC1, 4, 0, 0, 40, timeout=300))
            features, clock = struct.unpack_from("<II", caps)

            dev.ctrl_transfer(0x41, 0, 1, 0, struct.pack("<I", 0x0000BEEF), timeout=300)
            self.set_mode(dev, 0)

            # 16 time slices per bit, sample at 87.5%
            prescaler = round(clock / (self.bitrate * 16))
            dev.ctrl_transfer(0x41, 1, 0, 0, struct.pack("<5I", 1, 12, 2, 1, prescaler), timeout=300)

            # one shot mode drops frames nobody acks, otherwise the adapter jams
            # when the controller is off
            self.set_mode(dev, 1, 0x08 & features)
        except usb.core.USBError:
            self.let_go(dev)
            return False

        self.dev = dev
        self.stuck = 0
        return True

    def send(self, can_id, data):
        if not self.dev:
            return False
        packet = struct.pack("<IIBBBB8s", 0, can_id, len(data), 0, 0, 0, bytes(data).ljust(8, b"\0"))
        try:
            self.dev.write(EP_OUT, packet, timeout=20)
            self.stuck = 0
            return True
        except usb.core.USBError as e:
            if not timed_out(e):
                # unplugged
                self.close()
            else:
                self.stuck += 1
                # wedged, restarting the can channel fixes it without a replug
                if self.stuck > 20:
                    self.restart()
            return False

    def recv(self):
        while self.dev:
            try:
                raw = bytes(self.dev.read(EP_IN, 64, timeout=2))
            except usb.core.USBError as e:
                if not timed_out(e):
                    self.close()
                return None
            if len(raw) < 20:
                continue
            echo, can_id, length = struct.unpack_from("<IIB", raw)
            if echo != FROM_BUS or can_id & ERROR_FRAME:
                # our own frame coming back or an error
                continue
            return can_id & 0x7FF, raw[12:12 + min(length, 8)]
        return None

    def close(self):
        if self.dev:
            try:
                self.set_mode(self.dev, 0)
            except usb.core.USBError:
                pass
            self.let_go(self.dev)
        self.dev = None

    def restart(self):
        try:
            self.set_mode(self.dev, 0)
            self.set_mode(self.dev, 1, 0x08)
            self.stuck = 0
        except usb.core.USBError:
            self.close()

    @staticmethod
    def set_mode(dev, mode, flags=0):
        dev.ctrl_transfer(0x41, 2, 0, 0, struct.pack("<II", mode, flags), timeout=300)

    @staticmethod
    def let_go(dev):
        # release before dispose or the next open fails with access denied
        try:
            usb.util.release_interface(dev, 0)
        except Exception:
            pass
        usb.util.dispose_resources(dev)


def timed_out(e):
    return e.errno in (60, 110) or "timed out" in str(e).lower()
