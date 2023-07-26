import asyncio
import re

# possible HVAC modes
_MODES = ["auto", "cool", "dry", "fan", "heat"]
# possible FAN modes
FAN_SPEEDS = ['very low', 'low', 'medium', 'high', 'top', 'auto']

# The unit reports the above in one-letter codes (first letter):
_FAN_CHAR_TO_SPEED = {v[0]: v for v in FAN_SPEEDS}

MODES_TO_CHAR = {m[0]: m for m in _MODES}

_SWING_CHAR_TO_NAME = {
    "a": "auto",
    "h": "horizontal",
    "3": "30",
    "4": "45",
    "6": "60",
    "v": "vertical",
    "x": "stop",
}

_SWING_NAME_TO_CHAR = {value: key for key, value in _SWING_CHAR_TO_NAME.items()}

SWING_MODES = list(_SWING_CHAR_TO_NAME.values())

_PROPS_COLUMNS = ['uid', 'name', 'visibility', 'modes', 'fan_speeds']


class CoolMasterNet:
    """A connection to a coolmasternet bridge."""

    def __init__(self, host, port=10102, read_timeout=1, swing_support=False):
        """Initialize this CoolMasterNet instance to connect to a particular
        host at a particular port."""
        self._host = host
        self._port = port
        self._read_timeout = read_timeout
        self._swing_support = swing_support
        self._concurrent_reads = asyncio.Semaphore(3)
        self._props_data = None

    async def _make_request(self, request, timeout=None):
        """Send a request to the CoolMasterNet and returns the response."""
        timeout = timeout or self._read_timeout
        async with self._concurrent_reads:

            reader, writer = await asyncio.open_connection(self._host, self._port)

            try:
                prompt = await asyncio.wait_for(reader.readuntil(b">"), timeout)
                if prompt != b">":
                    raise ConnectionError("CoolMasterNet prompt not found")

                writer.write((request + "\n").encode("ascii"))
                response = await asyncio.wait_for(reader.readuntil(b"\n>"), timeout)

                data = response.decode("ascii")
                if data.endswith("\n>"):
                    data = data[:-1]

                if data.endswith("OK\r\n"):
                    data = data[:-4]

                return data
            finally:
                writer.close()
                await writer.wait_closed()

    async def info(self):
        """Get the general info of this CoolMasterNet."""
        raw = await self._make_request("set")
        lines = raw.strip().split("\r\n")
        key_values = [re.split(r"\s*:\s*", line, 1) for line in lines]
        self._props_data = await self._props()
        return dict(key_values)

    async def status(self):
        """Return a list of CoolMasterNetUnit objects with current status & properties."""
        if self._props_data is None:
            self._props_data = await self._props()  # only fetch once
        status_lines = (await self._make_request("ls2")).strip().split("\r\n")
        return {
            key: unit
            for unit, key in (await asyncio.gather(
                *(CoolMasterNetUnit.create(self, line[0:6], line, self._props_data[line[0:6]]) for line in
                  status_lines)))
        }

    async def _props(self):
        """ Returns properties of the units - modes, name, fan speeds as a dict
        unit_id->[name, visibility, modes, fan_modes]
        The unit id is the same as in the unit's dict. Note data is static and does not change over time."""
        props_lines = (await self._make_request("props")).strip().split("\r\n")
        if len(props_lines) < 3:
            return None
        props = {}
        for pline in props_lines[2:]:
            p_item = [p.strip() for p in pline.split("|")[0:5]]
            prop_dict = {m: p_item[i + 1] for i, m in enumerate(_PROPS_COLUMNS[1:])}
            prop_dict['modes'] = [MODES_TO_CHAR[c] for c in [y.strip() for y in prop_dict['modes'].split(' ') if y]]
            prop_dict['fan_speeds'] = [_FAN_CHAR_TO_SPEED[c] for c in
                                       [y.strip() for y in prop_dict['fan_speeds'].split(' ') if y]]
            props[p_item[0]] = prop_dict
        return props

    async def all_on(self):
        """Turn all units on. """
        """ Note: command sometimes fail on some of the units and might be needed to call more than once.
            due to issue with the bridge handling of this command"""
        await self._make_request("allon", timeout=10)

    async def all_off(self):
        """Turn all units off."""
        """ Note: command sometimes fail on some of the units and might be needed to call more than once.
            due to issue with the bridge handling of this command"""
        await self._make_request("alloff", timeout=10)


class CoolMasterNetUnit:
    """An immutable snapshot of a unit."""

    def __init__(self, bridge, unit_id, raw, swing_raw, props):
        """Initialize a unit snapshot."""
        self._raw = raw
        self._swing_raw = swing_raw
        self._unit_id = unit_id
        self._bridge = bridge
        self._parse()
        self._props = props

    @classmethod
    async def create(cls, bridge, unit_id, raw=None, props=None):
        if raw is None:
            raw = (await bridge._make_request(f"ls2 {unit_id}")).strip()
        swing_raw = ((await bridge._make_request(f"query {unit_id} s")).strip()
                     if bridge._swing_support else "")
        return CoolMasterNetUnit(bridge, unit_id, raw, swing_raw, props), unit_id

    def _parse(self):
        fields = re.split(r"\s+", self._raw.strip())
        if len(fields) != 9:
            raise ConnectionError("Unexpected status line format: " + str(fields))

        self._is_on = fields[1] == "ON"
        self._temperature_unit = "imperial" if fields[2][-1] == "F" else "celsius"
        self._thermostat = float(fields[2][:-1])
        self._temperature = float(fields[3][:-1])
        self._fan_speed = fields[4].lower()
        self._mode = fields[5].lower()
        self._error_code = fields[6] if fields[6] != "OK" else None
        self._clean_filter = fields[7] == "#"
        self._swing = _SWING_CHAR_TO_NAME.get(self._swing_raw)

    async def _make_unit_request(self, request):
        return await self._bridge._make_request(request.replace("UID", self._unit_id))

    async def refresh(self):
        """Refresh the data from CoolMasterNet and return it as a new instance."""
        return (await CoolMasterNetUnit.create(self._bridge, self._unit_id))[0]

    @property
    def unit_id(self):
        """The unit id."""
        return self._unit_id

    @property
    def is_on(self):
        """Is the unit on."""
        return self._is_on

    @property
    def thermostat(self):
        """The target temperature."""
        return self._thermostat

    @property
    def temperature(self):
        """The current temperature."""
        return self._temperature

    @property
    def fan_speed(self):
        """The fan speed."""
        return self._fan_speed

    @property
    def mode(self):
        """The current mode (e.g. heat, cool)."""
        return self._mode

    @property
    def error_code(self):
        """Error code on error, otherwise None."""
        return self._error_code

    @property
    def clean_filter(self):
        """True when the air filter needs to be cleaned."""
        return self._clean_filter

    @property
    def swing(self):
        """The current swing mode (e.g. horizontal)."""
        return self._swing

    @property
    def temperature_unit(self):
        return self._temperature_unit

    @property
    def fan_speeds(self):
        """ return available fan speeds for this unit """
        return self._props.get('fan_speeds', FAN_SPEEDS)

    @property
    def modes(self):
        """ return available modes for this unit """
        return self._props.get('modes', _MODES)

    @property
    def name(self):
        """ return friendly name of this unit """
        return self._props.get('name', '')

    async def set_fan_speed(self, value):
        """Set the fan speed."""
        await self._make_unit_request(f"fspeed UID {value}")
        return await self.refresh()

    async def set_mode(self, value):
        """Set the mode."""
        if value not in _MODES:
            raise ValueError(
                f"Unrecognized mode {value}. Valid values: {' '.join(_MODES)}"
            )
        await self._make_unit_request(value + " UID")
        return await self.refresh()

    async def set_thermostat(self, value):
        """Set the target temperature."""
        rounded = round(value, 1)
        await self._make_unit_request(f"temp UID {rounded}")
        return await self.refresh()

    async def set_swing(self, value):
        """Set the swing mode."""
        if not value in SWING_MODES:
            raise ValueError(
                f"Unrecognized swing mode {value}. Valid values: {', '.join(SWING_MODES)}"
            )

        return_value = await self._make_unit_request(f"swing UID {_SWING_NAME_TO_CHAR[value]}")
        if return_value.startswith("Unsupported Feature"):
            raise ValueError(
                f"Unit {self._unit_id} doesn't support swing mode {value}."
            )
        return await self.refresh()

    async def turn_on(self):
        """Turn a unit on."""
        await self._make_unit_request("on UID")
        return await self.refresh()

    async def turn_off(self):
        """Turn a unit off."""
        await self._make_unit_request("off UID")
        return await self.refresh()

    async def reset_filter(self):
        """Report that the air filter was cleaned and reset the timer."""
        await self._make_unit_request(f"filt UID")
        return await self.refresh()

    async def feed(self, value):
        """Provides ambient temperature hint to the unit."""
        rounded = round(value, 1)
        await self._make_unit_request(f"feed UID {rounded}")
