# iDrive Touch

Use a BMW iDrive touch controller as a trackpad and media controller on a Mac.

Touchpad, knob, tilt and all the buttons work.

Only tested on macOS.

## What you need

- BMW iDrive touch controller (the newer one with the touchpad, 500 kbps CAN)
- Power supply (12 V)
- USB-CAN adapter (tested with a candleLight)
- Python 3.9+
- libusb (`brew install libusb`)

## Wiring

| Wire colour    | Connect to        |
| -------------- | ----------------- |
| red / yellow   | PSU +             |
| brown / black  | PSU −             |
| orange / green | candleLight CAN H |
| green          | candleLight CAN L |

Turn the candleLight 120 Ω termination on. The controller doesn't have one.

## Setup

```
pip install -r requirements.txt
```

To control the Mac, allow your terminal in System Settings > Privacy & Security > Accessibility, then quit and reopen it.

## Run

Power on the controller and run:

```
python idrive.py
```

It prints every CAN frame with what it means. To control the Mac:

```
python idrive.py --mac
```

Press Ctrl+C to stop.

## Controls

| Controller           | Mac                              |
| -------------------- | -------------------------------- |
| one finger           | move the pointer                 |
| tap                  | click, tap twice to double click |
| tap, touch and move  | drag                             |
| two finger tap       | right click                      |
| two fingers up/down  | scroll                           |
| two fingers sideways | back / forward a page            |
| pinch                | zoom                             |
| turn the knob        | volume                           |
| push the knob        | play / pause                     |
| tilt left / right    | previous / next song             |
| tilt up              | Siri                             |
| tilt down            | Spotlight                        |
| menu                 | Mission Control                  |
| media                | Music                            |
| radio                | Apple Music playlists            |
| nav                  | Maps                             |
| tel                  | Messages                         |
| option               | right click                      |
| back                 | switch app                       |
