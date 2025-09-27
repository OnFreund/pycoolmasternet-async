# pycoolmasternet-async

A Python 3 library for interacting with a [CoolMasterNet](https://coolautomation.com/products/coolmasternet/) HVAC bridge.
This is a fork of [pycoolmaster](https://github.com/koreth/pycoolmasternet), modified to present an async interface and some other small changes.

## Installation

You can install pycoolmasternet-async from [PyPI](https://pypi.org/project/pycoolmasternet-async/):

    pip3 install pycoolmasternet-async

Python 3.13 and above are supported.


## How to use

```python
from pycoolmasternet_async import CoolMasterNet
cool = CoolMasterNet("coolmaster")

# Supply the IP address and optional port number (default 10102).
cool = CoolMasterNet("192.168.0.123", port=12345, read_timeout=1)

# General information
info = await cool.info()

# Returns a dict of CoolMasterNetUnit objects. Keys are the unit IDs
units = await cool.status()

unit = units["L1.001"]

unit.unit_id

# Temperature unit: Imperial, Celsius
unit.temperature_unit

# Current reading of unit's thermometer
unit.temperature

# Current setting of unit's thermostat
unit.thermostat

# Setters return a new instance with updated info
unit = await unit.set_thermostat(28)

# True if unit is turned on
unit.is_on
unit = await unit.turn_on()
unit = await unit.turn_off()

# Fan speed: low, med, high, auto
unit.fan_speed
unit = await unit.set_fan_speed('med')

# Mode of operation: auto, cool, dry, fan, heat
unit.mode
unit = await unit.set_mode('cool')

# Get fresh info
unit = await unit.refresh()

```
