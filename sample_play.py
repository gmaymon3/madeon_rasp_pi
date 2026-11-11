
import time
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from smbus import SMBus


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "Samples"

I2C_BUS = 1

MODULES = {
    "MCP1": 0x27,
    "MCP2": 0x26,
}

HEADPHONE_DEVICE = 1

BLOCK_SIZE = 2048
CHANNELS = 2

TRACK_GAIN = 0.20

GPIO_POLL_INTERVAL = 0.010
DEBOUNCE_TIME = 0.050
STATUS_INTERVAL = 0.500


# ============================================================
# SAMPLE MAPPING
# ============================================================

BUTTON_MAP = {}

# MCP1: GPA = drums, GPB = bass
for pin in range(8):
    BUTTON_MAP[(0x27, 0x12, pin)] = f"drum.1.{pin + 1}.wav"
    BUTTON_MAP[(0x27, 0x13, pin)] = f"bass.1.{pin + 1}.wav"

# MCP2: GPA = sounds 1-8, GPB = sounds 9-16
for pin in range(8):
    BUTTON_MAP[(0x26, 0x12, pin)] = f"sounds.1.{pin + 1}.wav"
    BUTTON_MAP[(0x26, 0x13, pin)] = f"sounds.1.{pin + 9}.wav"


# ============================================================
# LOAD SAMPLES
# ============================================================

tracks = {}

SAMPLE_RATE = None
SAMPLE_LENGTH = None

print("Loading samples...")

for filename in BUTTON_MAP.values():

    if filename in tracks:
        continue

    filepath = SAMPLE_DIR / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Missing sample: {filepath}")

    audio, samplerate = sf.read(
        filepath,
        dtype="float32",
        always_2d=True
    )

    if SAMPLE_RATE is None:
        SAMPLE_RATE = samplerate
        SAMPLE_LENGTH = len(audio)

    if samplerate != SAMPLE_RATE:
        raise ValueError(
            f"{filename} has sample rate {samplerate}, "
            f"expected {SAMPLE_RATE}"
        )

    if len(audio) != SAMPLE_LENGTH:
        raise ValueError(
            f"{filename} has {len(audio)} frames, "
            f"expected {SAMPLE_LENGTH}. "
            "All samples must have identical lengths."
        )

    # Convert to stereo
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)

    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    tracks[filename] = {
        "audio": audio,
        "on": False,
        "playing": False,
    }

print(f"Loaded {len(tracks)} samples")
print(f"Sample rate: {SAMPLE_RATE} Hz")
print(f"Sample duration: {SAMPLE_LENGTH / SAMPLE_RATE:.3f} seconds")


# ============================================================
# AUDIO ENGINE STATE
# ============================================================

audio_lock = threading.Lock()

loop_position = 0
loop_running = False

audio_underflows = 0


# ============================================================
# AUDIO CALLBACK
# ============================================================

def audio_callback(outdata, frames, time_info, status):

    global loop_position
    global loop_running
    global audio_underflows

    if status:
        audio_underflows += 1

    outdata.fill(0)

    with audio_lock:

        output_position = 0

        while output_position < frames:

            # Nothing is currently playing
            if not loop_running:
                break

            # Number of frames remaining in this loop
            remaining = SAMPLE_LENGTH - loop_position

            # Number of frames to process in this callback
            count = min(
                frames - output_position,
                remaining
            )

            start_out = output_position
            end_out = output_position + count

            start_sample = loop_position
            end_sample = loop_position + count

            # Mix every currently playing sample
            for track in tracks.values():

                if not track["playing"]:
                    continue

                sample = track["audio"][
                    start_sample:end_sample
                ]

                outdata[start_out:end_out] += (
                    sample * TRACK_GAIN
                )

            output_position += count
            loop_position += count

            # ------------------------------------------------
            # SHARED LOOP BOUNDARY
            # ------------------------------------------------

            if loop_position >= SAMPLE_LENGTH:

                loop_position = 0

                any_playing = False

                for track in tracks.values():

                    # All enabled tracks start together
                    track["playing"] = track["on"]

                    if track["playing"]:
                        any_playing = True

                # Stop the shared loop if everything is OFF
                if not any_playing:
                    loop_running = False

        # Simple peak protection
        peak = np.max(np.abs(outdata))

        if peak > 0.98:
            outdata *= 0.98 / peak


# ============================================================
# BUTTON HANDLING
# ============================================================

def toggle_track(filename):

    global loop_position
    global loop_running

    with audio_lock:

        track = tracks[filename]

        track["on"] = not track["on"]

        # If the audio engine is idle, start immediately
        if track["on"] and not loop_running:

            loop_position = 0
            loop_running = True

            # Start all currently enabled tracks
            for t in tracks.values():
                t["playing"] = t["on"]

        # If the engine is already running:
        # Newly enabled tracks wait for the next boundary.
        #
        # Disabled tracks finish their current cycle.

        enabled = track["on"]

    print(
        f"{filename}: {'ON' if enabled else 'OFF'}"
    )


# ============================================================
# MCP23017 INITIALIZATION
# ============================================================

bus = SMBus(I2C_BUS)


def initialize_mcp(address):

    # Configure all pins as inputs
    bus.write_byte_data(address, 0x00, 0xFF)
    bus.write_byte_data(address, 0x01, 0xFF)

    # Enable internal pull-up resistors
    bus.write_byte_data(address, 0x0C, 0xFF)
    bus.write_byte_data(address, 0x0D, 0xFF)


for name, address in MODULES.items():

    initialize_mcp(address)

    print(f"{name} initialized at 0x{address:02X}")


# ============================================================
# BUTTON DEBOUNCING
# ============================================================

button_states = {}

for key in BUTTON_MAP:

    button_states[key] = {
        "raw": False,
        "stable": False,
        "last_change": time.monotonic(),
    }


def poll_buttons():

    now = time.monotonic()

    for name, address in MODULES.items():

        # Read both GPIO ports
        gpio_a = bus.read_byte_data(address, 0x12)
        gpio_b = bus.read_byte_data(address, 0x13)

        for port_reg, gpio_value in (
            (0x12, gpio_a),
            (0x13, gpio_b),
        ):

            for pin in range(8):

                key = (address, port_reg, pin)

                # Active LOW: button pressed = True
                pressed = not bool(
                    gpio_value & (1 << pin)
                )

                state = button_states[key]

                # Detect raw state changes
                if pressed != state["raw"]:

                    state["raw"] = pressed
                    state["last_change"] = now

                # Wait for stable state
                elif (
                    pressed != state["stable"]
                    and now - state["last_change"] >= DEBOUNCE_TIME
                ):

                    state["stable"] = pressed

                    # Only toggle on button press
                    if pressed:

                        filename = BUTTON_MAP[key]
                        toggle_track(filename)


# ============================================================
# STATUS DISPLAY
# ============================================================

def print_status():

    with audio_lock:

        snapshot = {
            filename: (
                track["on"],
                track["playing"]
            )
            for filename, track in tracks.items()
        }

        position = loop_position
        running = loop_running

    print("\033[2J\033[H", end="")

    print("======================================")
    print("          MADEON SAMPLE PLAYER")
    print("======================================")

    if running:
        progress = position / SAMPLE_LENGTH * 100
        print(f"Loop progress: {progress:.1f}%")
    else:
        print("Playback stopped")

    print()

    for filename, (enabled, playing) in snapshot.items():

        if enabled and playing:
            status = "PLAYING"

        elif enabled and not playing:
            status = "QUEUED"

        elif not enabled and playing:
            status = "FINISHING"

        else:
            status = "OFF"

        print(f"{filename:22} {status}")

    print()
    print("Press buttons to toggle samples.")
    print("Ctrl+C to exit.")


# ============================================================
# MAIN
# ============================================================

def main():

    global audio_underflows

    print("Starting audio engine...")

    try:

        with sd.OutputStream(
            device=HEADPHONE_DEVICE,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            latency="high",
            callback=audio_callback,
        ):

            print("Audio engine running.")
            print("Waiting for button presses...")

            last_status = time.monotonic()

            while True:

                poll_buttons()

                now = time.monotonic()

                if now - last_status >= STATUS_INTERVAL:

                    print_status()

                    if audio_underflows:
                        print(
                            f"Audio callback warnings: "
                            f"{audio_underflows}"
                        )
                        audio_underflows = 0

                    last_status = now

                time.sleep(GPIO_POLL_INTERVAL)

    except KeyboardInterrupt:

        print("\nStopping sample player...")

    finally:

        bus.close()


if __name__ == "__main__":
    main()
