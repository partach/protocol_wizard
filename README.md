# Protocol Wizard for Home Assistant
[![Home Assistant](https://img.shields.io/badge/Home_Assistant-00A1DF?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![HACS](https://img.shields.io/badge/HACS-Default-41BDF5?style=flat-square)](https://hacs.xyz)
[![HACS Action](https://img.shields.io/github/actions/workflow/status/partach/protocol_wizard/validate-hacs.yml?label=HACS%20Action&style=flat-square)](https://github.com/partach/protocol_wizard/actions)
[![Installs](https://img.shields.io/github/downloads/partach/protocol_wizard/total?color=28A745&label=Installs&style=flat-square)](https://github.com/partach/protocol_wizard/releases)
[![License](https://img.shields.io/github/license/partach/protocol_wizard?color=ffca28&style=flat-square)](https://github.com/partach/protocol_wizard/blob/main/LICENSE)
[![HACS validated](https://img.shields.io/badge/HACS-validated-41BDF5?style=flat-square)](https://github.com/hacs/integration)

The Protocol Wizard helps you build your home assistant devices without need for any yaml!

**Configure and control devices entirely from the UI — no YAML, no restarts!**<br>

Protocol Wizard lets you discover, test, and integrate devices (Modbus, SNMP) directly in Home Assistant — all through a simple, powerful interface.<br>
All run-time!

<p align="center">
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-config1.png" width="600" alt="Runtime entity configuration"/>
  <br><em>Add and configure sensors at runtime — no reboots required</em>
</p>

**Work in progress — actively developed and improving!**

## Features

- **Zero YAML configuration** — everything done via the Home Assistant UI
- Device templates support! Just present your device as a json template! (see below)
- Full support for **serial (RS485/USB)** and **IP-based (TCP & UDP)**
- **Runtime entity management** — add, edit, or remove sensors without restarting HA
- Dedicated **Lovelace cards** for live reading/writing any register/OID/etc. (perfect for testing and debugging)
- Create only the entities you need — keep your setup clean and efficient
- Modbus: **Multiple slaves** supported (up to 255 per bus/network) with individual slave IDs
- Modbus: **Multiple masters** possible (HA as master; coexists with other masters if no conflicts)
- Configurable refresh intervals per device
- Full automation support — use sensors in automations, scripts, and dashboards
- Advanced options: scaling, offset, byte/word order, endianness, bit handling, and more

<p align="center">
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-card.png" width="350" alt="Modbus Wizard Card"/>
  <br><em>Probe and control any register in real-time with the included card</em>
</p>

## Installation

### Option 1: HACS (Recommended — coming soon)
Once available in HACS default repository, install with one click.

### Option 2: Manual Install
1. Go to **HACS → Integrations → ⋮ → Custom repositories**
2. Add repository:  
   URL: `https://github.com/partach/protocol_wizard`  
   Category: **Integration**
3. Click **Add**
4. Go to devices and service, add integration, Search for "Protocol Wizard" and install.
5. **Restart Home Assistant**
6. Go to **Settings → Devices & Services → + Add Integration** → Search for **Protocol Wizard**

> The included Lovelace card is automatically registered on startup.  
> A browser refresh may be needed the first time to see it.

## Setup Guide

### RS485 Termination Note for Modbus devices
For reliable serial Modbus (RS485), install **120Ω termination resistors** at **both ends** of the bus only.  
Too many resistors degrade the signal; none can cause reflections and errors.

<p align="center">
  <img src="https://github.com/partach/ha_modbus_wizard/raw/main/120ohm.png" width="600" alt="120 ohm"/>
  <br><em>how to apply the 120 ohm resistor with multiple devices attached on the bus</em>
</p>

### Step 1: Select your protocol
1. Click **+ Add Integration** → Choose **Protocol Wizard**
2. Select Modbus / SNMP / etc.

<p align="center">
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-config3.png" width="600" alt="Runtime entity configuration"/>
  <br><em>Choose Protocol - no restarts required</em>
</p>

### Step 2: Add Your Device (Modbus Example shown)
1. Select connection type: **Serial** or **IP (TCP/UDP)**
2. Enter:
   - Slave ID (usually 1)
   - A test register address (often 0 or 30001 → use 0 in the integration)
   - Test register size (usually 1 or 2)
3. Provide connection details (port, baudrate, host, etc.)
4. The integration will auto-test connectivity

→ Success? You're ready!

<p align="center">
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-config4.png" width="300" alt="Step 1"/>
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-config8.png" width="400" alt="Step 2"/>
  <br><em>Simple device setup</em>
</p>

### Step 3: Explore with the Card (Recommended for Discovery)
Add the **Protocol Wizard Card** to a dashboard:
- Edit dashboard → Add card → Search for **"Protocol Wizard Card"**
- Select your device (depending on type of device the UI of the card adapts)
! You need to have a card per device (To ensure you are communicating with the right device)

Now you can:
- Read any register instantly
- Write values to test device behavior
- Experiment with data types, byte order, and scaling

Perfect for reverse-engineering undocumented devices!

### Step 4: Create Permanent Sensors
Once you know which registers you want:
- Go to your Protocol Wizard device → **Configure** → **Add register**

<p align="center">
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-config5.png" width="600" alt="Runtime entity configuration"/>
  <br><em>Add and/or configure your device, add/delete/edit entities</em>
</p>
- Fill in name, address, data type, unit, scaling, etc.
- Advanced options available (click "Show advanced options")

<p align="center">
  <img src="https://github.com/partach/protocol_wizard/raw/main/pictures/pwz-config6.png" width="400" alt="Add register form"/>
  <br><em>Full control over sensor configuration</em>
</p>

Your new sensors appear immediately — no restart needed.  
You can later edit or delete them from the same options menu.

## Device Templates
Via the hub configuration (gear symbol) you can read device templates (in standard JSON format).
These are easy to make (AI can be your friend) and help you import your device (or change) run-time with a few clicks.
SDM630 basic profile is provided in the code. Just feed this to Grok, ChatGPT, Claude, etc. And ask to get this for device X/Y.
Then add to the template directory of the integration `/custom_components/protocol_wizard/templates/mydevicename.json
Also send them to me so i can possibly add them for a next release :)

The Format (entry per register)
```
[
  {
    "name": "Phase 1 Voltage",
    "address": 0,
    "data_type": "float32",
    "register_type": "input",
    "rw": "read",
    "unit": "V",
    "scale": 1.0,
    "offset": 0.0,
    "byte_order": "big",
    "word_order": "big",
    "allow_bits": false
  }
]
```
SNMP example
```
[
  {
    "name": "System Description",
    "address": "1.3.6.1.2.1.1.1.0",
    "data_type": "string",
    "read_mode": "get"
  },
  {
    "name": "System Uptime",
    "address": "1.3.6.1.2.1.1.3.0",
    "data_type": "integer",
    "read_mode": "get"
  },
  {
    "name": "System Name",
    "address": "1.3.6.1.2.1.1.5.0",
    "data_type": "string",
    "read_mode": "get"
  },
  {
    "name": "Interface Speeds",
    "address": "1.3.6.1.2.1.2.2.1.5",
    "read_mode": "walk"
  }
]
```

## Register Configuration Fields (Modbus)

When adding or editing a register, the following fields are available:

| Field              | Required | Default       | Description                                                                                                      |
|--------------------|----------|---------------|------------------------------------------------------------------------------------------------------------------|
| **name**           | Yes      | -             | Human-readable name for the entity                                                                               |
| **address**        | Yes      | -             | Modbus register address (0–65535)                                                                                |
| **data_type**      | Yes      | `uint16`      | How to decode the value: `uint16`, `int16`, `uint32`, `int32`, `float32`, `uint64`, `int64`                        |
| **register_type**  | Yes      | `input`       | Function code: `auto`, `holding`, `input`, `coil`, `discrete`                                                    |
| **rw**             | Yes      | `read`        | Entity type: `read` (sensor), `write` (number), `rw` (both)                                                       |
| **unit**           | No       | -             | Unit of measurement (e.g., "V", "A", "W")                                                                        |
| **scale**          | No       | `1.0`         | Multiplier applied after decoding (`value × scale + offset`)                                                     |
| **offset**         | No       | `0.0`         | Additive offset after scaling                                                                                    |
| **options**        | No       | -             | JSON mapping for select entity (e.g., `{"0": "Off", "1": "On"}`)                                                 |
| **byte_order**     | No       | `big`         | Byte order within each word (big/little)                                                                         |
| **word_order**     | No       | `big`         | Order of the 16-bit words (big/little) for multi-register values                                                 |
| **format**         | No       | -             | python formating for read values like {d}d {h}h {m}m for seconds to human readible value                         |
| **min**            | No       | -             | Minimum value for writeable number entities                                                                       |
| **max**            | No       | -             | Maximum value for writeable number entities                                                                       |
| **step**           | No       | `1.0`         | Step size for number entity adjustments                                                                          |

### Quick Tips for Common Use Cases
- **Voltages/Currents**: `data_type = "uint16"`, `scale = 0.1` or `0.01`, unit "V"/"A"
- **Power**: Often `uint32` or `float32` with appropriate scaling
- **Status bits**: Use `coil`/`discrete` + `options` JSON for friendly names

## Why Choose Protocol Wizard?

- **No more YAML hell** — perfect for devices with poor documentation
- **Fast iteration** — test registers live, then save only what you need
- **Beginner-friendly** yet powerful for advanced users
- **Full control** — bit-level access, custom scaling, endianness, raw mode

## Roadmap & Planned Features
- More **Templates for common devices**: Pre-load register sets for popular boards like WaveShare RS485 series (save typing, reduce errors)
- **Enhanced card display**: Support also SNMP, for Modbus enhancements, other protocols
- **Diagnostic export**: One-click YAML/JSON report of all registers and values for troubleshooting

## Support & Feedback

This integration is under active development. Found a bug? Have a feature request?

→ Open an issue on GitHub: https://github.com/partach/protocol_wizard/issues

Contributions welcome!

### Discussion
Join the conversation: [GitHub Discussions](https://github.com/partach/protocol_wizard/discussions)

### Changelog
See [CHANGELOG.md](https://github.com/partach/protocol_wizard/blob/main/CHANGELOG.md)

### Support Development
If you find Protocol Wizard useful, consider buying me a coffee! ☕

[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg?style=flat-square)](https://paypal.me/therealbean)

---

**Made with ❤️ for the Home Assistant community**
