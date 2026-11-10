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


def print_pins(module, gpio_a, gpio_b):

    print(f"\n{module}")
    print("-" * 30)

    for port, value in [("GPA", gpio_a), ("GPB", gpio_b)]:
        for pin in range(8):
            state = (value >> pin) & 1
            status = "HIGH" if state else "LOW"

            print(f"{port}{pin}: {status}")


# Initialize both modules
for address in MODULES.values():
    setup_module(address)


try:
    while True:
        print("\n" + "=" * 35)
        print("       MCP23017 GPIO STATUS")
        print("=" * 35)

        for module, address in MODULES.items():
            gpio_a, gpio_b = read_module(address)
            print_pins(module, gpio_a, gpio_b)

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nMonitoring stopped.")

finally:
    bus.close()
