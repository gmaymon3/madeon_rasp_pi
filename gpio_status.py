import smbus
import time

# I2C configuration
bus = smbus.SMBus(1)

MODULES = {
    "MCP1": 0x27,
    "MCP2": 0x26
}

# MCP23017 registers
IODIRA = 0x00
IODIRB = 0x01
GPPUA  = 0x0C
GPPUB  = 0x0D
GPIOA  = 0x12
GPIOB  = 0x13

# Timing
POLL_INTERVAL = 0.01
DEBOUNCE_TIME = 0.05

# Track button states
button_states = {}
previous_inputs = {}
last_change_time = {}


def setup_module(address):
    # Configure all 16 pins as inputs
    bus.write_byte_data(address, IODIRA, 0xFF)
    bus.write_byte_data(address, IODIRB, 0xFF)

    # Enable internal pull-up resistors
    bus.write_byte_data(address, GPPUA, 0xFF)
    bus.write_byte_data(address, GPPUB, 0xFF)


def read_module(address):
    gpio_a = bus.read_byte_data(address, GPIOA)
    gpio_b = bus.read_byte_data(address, GPIOB)

    return gpio_a, gpio_b


def initialize_buttons():
    # Initialize every button as OFF
    for module, address in MODULES.items():
        gpio_a, gpio_b = read_module(address)

        for port, value in [("GPA", gpio_a), ("GPB", gpio_b)]:
            for pin in range(8):
                name = f"{module}_{port}{pin}"

                # Electrical input state: 1 = released, 0 = pressed
                previous_inputs[name] = (value >> pin) & 1

                # Logical toggle state
                button_states[name] = False

                last_change_time[name] = time.monotonic()


def update_button(name, current_input):
    now = time.monotonic()

    if current_input != previous_inputs[name]:
        last_change_time[name] = now
        previous_inputs[name] = current_input
        return

    # Detect a stable LOW (pressed) transition
    if current_input == 0:
        if now - last_change_time[name] >= DEBOUNCE_TIME:
            if not button_states.get(f"{name}_pressed", False):
                button_states[name] = not button_states[name]
                button_states[f"{name}_pressed"] = True

    else:
        # Button released; allow another press
        button_states[f"{name}_pressed"] = False


def print_pins():
    print("\033[H\033[J", end="")  # Clear terminal

    print("=" * 45)
    print("          MCP23017 BUTTON STATUS")
    print("=" * 45)

    for module, address in MODULES.items():
        gpio_a, gpio_b = read_module(address)

        print(f"\n{module} (0x{address:02X})")
        print("-" * 35)

        for port, value in [("GPA", gpio_a), ("GPB", gpio_b)]:
            for pin in range(8):
                name = f"{module}_{port}{pin}"
                current_input = (value >> pin) & 1

                update_button(name, current_input)

                status = "ON " if button_states[name] else "OFF"

                print(f"{port}{pin}: {status}")


# Initialize both modules
for address in MODULES.values():
    setup_module(address)

# Initialize button tracking
initialize_buttons()

try:
    while True:
        print_pins()
        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    print("\nMonitoring stopped.")

finally:
    bus.close()
