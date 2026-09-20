# Setting up `videomode` on a new Raspberry Pi

Target hardware: Raspberry Pi 3B, Adafruit RGB Matrix Bonnet, two chained
64×32 P6 HUB75 panels (128×32 total), three GPIO buttons (left flipper,
right flipper, fire/launch). Runs headless — all interaction is through the
DMD and buttons, no monitor needed after setup.

These instructions assume the conventions already baked into this repo:
hostname `[hostname]`, user `[username]`, project checked out to `~/videomode`,
venv at `~/env`.

---

## 1. Flash and boot the Pi

1. Flash **Raspberry Pi OS Lite (64-bit)** to an SD card using Raspberry Pi
   Imager.
2. In the Imager's advanced options (or via `firstrun.sh`), set:
   - hostname: `[hostname]`
   - username: `[username]`
   - enable SSH
   - configure Wi-Fi / locale as needed
3. Boot the Pi and SSH in:
   ```bash
   ssh [username]@[hostname].local
   ```
4. Update the system:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```

## 2. Enable required interfaces

The LED matrix and buttons need SPI/GPIO access, and the matrix driver
wants sound disabled (it conflicts with the PWM timer the matrix library
uses):

```bash
sudo raspi-config
```
- **Interface Options** → SPI → Enable
- **Performance Options** → confirm GPU memory split is fine at default

Disable onboard audio (frees the PWM hardware the LED panel needs):
```bash
sudo tee /etc/modprobe.d/blacklist-snd-bcm2835.conf <<'EOF'
blacklist snd_bcm2835
EOF
sudo reboot
```

This step is required regardless of which matrix mode you run (see step 5a)
— the Bonnet's PWM output and the Pi's onboard audio share the same
hardware peripheral, so the audio driver has to stay out of the way.

## 3. Install system packages

```bash
sudo apt install -y \
  git build-essential cmake python3-venv python3-pip \
  liblgpio-dev \
  libsdl2-dev libasound2-dev libpulse-dev   # audio/video deps for pinmame build
```

## 4. Wire the hardware

- Adafruit RGB Matrix Bonnet seated on the Pi's GPIO header.
- Two 64×32 P6 panels chained horizontally (panel 1 IN → Pi/bonnet,
  panel 1 OUT → panel 2 IN).
- Three buttons wired to BCM pins (active-low, internal pull-up — no
  external resistors needed):

  | Button          | BCM pin |
  |-----------------|---------|
  | Left flipper    | 25      |
  | Right flipper   | 19      |
  | Fire / launch   | 7       |

  These are deliberately *not* 17/22/27 — those conflict with HUB75
  signals used by the Adafruit bonnet.

## 5. Build `rpi-rgb-led-matrix` (hzeller)

Must be built from source; the pip package alone isn't enough since we
need it running as root with hardware PWM.

```bash
cd ~
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix
make build-python PYTHON=$(which python3)
sudo make install-python PYTHON=$(which python3)
```

This installs the `rgbmatrix` Python module system-wide. Because the
matrix driver needs raw GPIO timing, the app runs as root — `dmd_display.py`
already sets `drop_privileges = False` in `MATRIX_OPTIONS` so the library
doesn't drop root after mmapping GPIO memory.

By default the project runs the Bonnet in **"convenience" mode**
(`hardware_mapping = "adafruit-hat"`, `disable_hardware_pulsing = True` in
`dmd_display.py`) — no extra wiring needed, at the cost of occasional
visible flicker. If flicker is a problem, see the optional step below.

### 5a. Optional: enable hardware pulsing ("quality" mode) to reduce flicker

Adafruit's installer calls this the "quality" option: it trades a
soldering step for smoother, less flickery output by giving the matrix
library a dedicated hardware PWM channel instead of timing pulses in
software. **No library rebuild is needed for this** —
`hardware_mapping` and `disable_hardware_pulsing` are runtime options read
by the Python bindings each time the app starts, not compile-time flags.
Only wiring and a couple of OS-level checks change.

1. **Power off the Pi, then solder a jumper wire between GPIO4 and GPIO18**
   on the Bonnet. This routes a second hardware PWM channel to the pin the
   matrix library needs for hardware-pulsed output. Check the Bonnet's
   silkscreen for the two pads if you're not going straight off the header
   pin numbers.

2. **Confirm onboard audio is still disabled.** Step 2 above already
   blacklists `snd_bcm2835`, which is required for quality mode too —
   verify it stuck:
   ```bash
   lsmod | grep snd_bcm2835
   ```
   No output means it's already disabled and you can skip ahead. If it
   prints a line, re-run the blacklist step above and reboot before
   continuing.

3. **(Optional — only if flicker/jitter remains after the jumper) isolate a
   CPU core** for the matrix library's realtime GPIO thread. This is a
   tuning step, not a requirement; a single 128×32 chain on a Pi 3B usually
   doesn't need it, but it's worth trying here since PinMAME emulation is
   competing for CPU on the same board:
   ```bash
   sudo sed -i '$ s/$/ isolcpus=3/' /boot/firmware/cmdline.txt
   sudo reboot
   ```
   (On older Pi OS releases the file is at `/boot/cmdline.txt` instead of
   `/boot/firmware/cmdline.txt`.)

4. **Update `MATRIX_OPTIONS` in `dmd_display.py`:**
   ```python
   MATRIX_OPTIONS: dict = dict(
       rows                     = 32,
       cols                     = 64,
       chain_length             = 2,
       parallel                 = 1,
       hardware_mapping         = "adafruit-hat-pwm",  # was "adafruit-hat"
       gpio_slowdown            = 4,
       brightness               = 30,
       disable_hardware_pulsing = False,                # was True
       drop_privileges          = False,
   )
   ```

5. **Restart the app** to pick up the change:
   ```bash
   sudo systemctl restart videomode.service
   ```
   No reboot is needed for this step by itself — only step 3 above (if you
   used it) requires one, since it edits the boot command line.

If you still see garbled or misaligned pixels (not flicker) after
soldering, try raising `gpio_slowdown` — hardware pulsing draws more
current and can be more sensitive to signal timing than convenience mode.

## 6. Build `libpinmame.so` (vpinball/pinmame)

```bash
cd ~
git clone --recursive https://github.com/vpinball/pinmame.git
cd pinmame
cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIB=ON
cmake --build build -j$(nproc)
```

This produces `~/pinmame/build/libpinmame.so`. A Pi 3B build can take a
while (~20-30 min) — consider cross-compiling or building on a faster
machine and copying the `.so` over if this is too slow.

## 7. Check out the project and set up the venv

```bash
cd ~
git clone <videomode-repo-url> videomode
cd videomode

python3 -m venv ~/env
source ~/env/bin/activate

pip install --upgrade pip --break-system-packages
pip install -e . --break-system-packages
pip install numpy lgpio --break-system-packages
```

- `numpy` is required for the 192×64 → 128×32 frame resampling in
  `dmd_display.py`.
- `lgpio` is the GPIO backend `gpiozero` uses on modern Pi OS; the
  `liblgpio-dev` apt package installed in step 3 is its native dependency.

## 8. Set up `~/.pinmame`

```bash
mkdir -p ~/.pinmame/roms ~/.pinmame/nvram ~/.pinmame/sta
```

- Copy your ROM zip files into `~/.pinmame/roms/` (must match the `rom`
  fields in `games.json`, e.g. `t2_l8.zip`).
- `players.json`, `scores.json`, and `settings.json` will be created
  automatically on first run in the project directory (or wherever
  `DEFAULT_*_PATH` in each store module resolves, unless overridden).
- Snapshot `.sta` files go in `~/.pinmame/sta/` — see step 10.

## 9. Point the app at `libpinmame.so`

The library search order (see `pinmame/_lib.py`) checks, in order: an
explicit path, `LIBPINMAME_PATH` env var, a `LIBPINMAME_PATH` attribute on
`__main__`, `ctypes.util.find_library`, then well-known paths including
`~/pinmame/build/libpinmame.so` — which is exactly where step 6 put it, so
no extra configuration is normally needed. If you built it somewhere else:

```bash
export LIBPINMAME_PATH=/path/to/libpinmame.so
```

## 10. Create snapshots for each game

Video mode playback replays a saved PinMAME state, so each ready game in
`games.json` needs a `.sta` snapshot at
`~/.pinmame/sta/<rom>-<snapshot_index>.sta` before it'll show as playable.

Run the snapshotter interactively (needs a terminal, not headless yet):
```bash
source ~/env/bin/activate
cd ~/videomode
python videomode.py --snapshotter
```
Use the on-screen keys to navigate the ROM to the moment a video mode
begins, then press Enter to capture the snapshot. Repeat for each
video mode listed in `games.json`.

## 11. Test it manually before wiring up systemd

```bash
source ~/env/bin/activate
cd ~/videomode
sudo -E env "PATH=$PATH" python videomode.py
```
(`sudo` is required for GPIO/matrix timing; `-E` preserves the venv's
`PATH` so it still finds the venv's Python and packages.)

You should see the login screen on the DMD and be able to navigate with
the flipper buttons. If you don't have hardware attached yet, or want to
test on a desktop, set:
```bash
export DMD_TO_TERMINAL=1
```
and it'll render frames to the terminal instead of the LED matrix.

## 12. Install the systemd service

Create `/etc/systemd/system/videomode.service`:

```ini
[Unit]
Description=videomode pinball arcade player
After=network.target sound.target

[Service]
Type=simple
User=root
Environment=HOME=/home/[username]
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/home/[username]/videomode
ExecStart=/home/[username]/env/bin/python /home/[username]/videomode/videomode.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Notes on the settings above (each fixes a real bug hit during
development):
- **`User=root`** — required for correct GPIO/matrix timing; the matrix
  library normally drops root after mmapping GPIO memory, but
  `drop_privileges = False` in `dmd_display.py` keeps it elevated.
- **`Environment=HOME=/home/[username]`** — without this, `Path.home()`
  resolves to `/root` under systemd (root's own service context), which
  breaks every path derived from it (`~/.pinmame`, snapshots, scores,
  etc). On Python 3.13+ this surfaces as a hard `PermissionError` from
  `Path.exists()` rather than silently returning `False`, so don't skip
  this.
- **`PYTHONUNBUFFERED=1`** — so logs show up promptly in journald instead
  of being buffered.

Enable and start it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable videomode.service
sudo systemctl start videomode.service
```

Check logs:
```bash
journalctl -u videomode.service -f
```
(the app also writes its own rotating log to `videomode.log` in the
working directory via the `logging` config in `videomode.py`.)

## 13. Reboot and confirm it comes up headless

```bash
sudo reboot
```

After boot, the DMD should show the login screen with no manual
intervention. If it doesn't:
- `systemctl status videomode.service` — check for a crash loop
- `journalctl -u videomode.service -n 100 --no-pager` — check recent logs
- Confirm `~/.pinmame/roms/<rom>.zip` files exist and match `games.json`
- Confirm snapshots exist for any game marked `"ready": true`

---

## Known gotchas checklist

- [ ] Onboard audio blacklisted (frees PWM for the matrix)
- [ ] Buttons wired to BCM 25 / 19 / 7, *not* 17/22/27
- [ ] `rpi-rgb-led-matrix` built from source, not just `pip install rgbmatrix`
- [ ] `drop_privileges = False` present in `MATRIX_OPTIONS` (already in repo)
- [ ] Decided "convenience" vs "quality" (soldered GPIO4–18 jumper) mode, and
      confirmed `hardware_mapping` / `disable_hardware_pulsing` in
      `dmd_display.py` actually match which one you wired up (see step 5a)
- [ ] systemd unit runs as root with `Environment=HOME=/home/[username]` set
- [ ] `pip install` used `--break-system-packages` (Pi OS Bookworm+ blocks
      unmanaged system-wide installs otherwise)
- [ ] Snapshots exist in `~/.pinmame/sta/` for every game marked ready