"""Standard SAE J1979 mode 01 parameters that SmartDrive reads, with their decoding formulas.

Only parameters listed here can be requested (see :mod:`smartdrive.obd.commands`). Each decoder
receives the data bytes after the ``41 <pid>`` echo and returns a value in SmartDrive's metric
units. Oil pressure has no standard mode 01 PID, so it is never available over generic OBD-II.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

Decoder = Callable[[bytes], float]


def _a(data: bytes) -> int:
    return data[0]


def _ab(data: bytes) -> int:
    return data[0] * 256 + data[1]


def _pct(data: bytes) -> float:
    return _a(data) * 100.0 / 255.0


def _temp(data: bytes) -> float:
    return float(_a(data) - 40)


def _trim(data: bytes) -> float:
    return (_a(data) - 128) * 100.0 / 128.0


@dataclass(frozen=True, slots=True)
class PidSpec:
    pid: int
    name: str
    label: str
    unit: str
    length: int
    decode: Decoder
    sample_field: str | None = None
    """``TelemetrySample`` field this PID fills, or ``None`` for values kept in ``extra``."""
    extra_key: str | None = None

    @property
    def request(self) -> str:
        return f"01{self.pid:02X}"

    @property
    def key(self) -> str:
        return self.sample_field or self.extra_key or self.name


DATA_PIDS: Final[tuple[PidSpec, ...]] = (
    PidSpec(0x04, "engine_load", "Calculated engine load", "%", 1, _pct, "engine_load_pct"),
    PidSpec(0x05, "coolant_temp", "Engine coolant temperature", "°C", 1, _temp, "coolant_temp_c"),
    PidSpec(0x06, "stft_b1", "Short-term fuel trim, bank 1", "%", 1, _trim, None, "stft_b1_pct"),
    PidSpec(0x07, "ltft_b1", "Long-term fuel trim, bank 1", "%", 1, _trim, None, "ltft_b1_pct"),
    PidSpec(0x08, "stft_b2", "Short-term fuel trim, bank 2", "%", 1, _trim, None, "stft_b2_pct"),
    PidSpec(0x09, "ltft_b2", "Long-term fuel trim, bank 2", "%", 1, _trim, None, "ltft_b2_pct"),
    PidSpec(
        0x0B,
        "intake_map",
        "Intake manifold absolute pressure",
        "kPa",
        1,
        lambda d: float(_a(d)),
        None,
        "map_kpa",
    ),
    PidSpec(0x0C, "rpm", "Engine speed", "rpm", 2, lambda d: _ab(d) / 4.0, "rpm"),
    PidSpec(0x0D, "speed", "Vehicle speed", "km/h", 1, lambda d: float(_a(d)), "speed_kph"),
    PidSpec(0x0F, "intake_temp", "Intake air temperature", "°C", 1, _temp, "intake_air_temp_c"),
    PidSpec(0x10, "maf", "Mass air flow rate", "g/s", 2, lambda d: _ab(d) / 100.0, None, "maf_gps"),
    PidSpec(0x11, "throttle", "Throttle position", "%", 1, _pct, "throttle_pct"),
    PidSpec(
        0x1F,
        "run_time",
        "Run time since engine start",
        "s",
        2,
        lambda d: float(_ab(d)),
        None,
        "engine_run_time_s",
    ),
    PidSpec(0x2F, "fuel_level", "Fuel tank level input", "%", 1, _pct, "fuel_level_pct"),
    PidSpec(
        0x33,
        "barometric",
        "Absolute barometric pressure",
        "kPa",
        1,
        lambda d: float(_a(d)),
        None,
        "baro_kpa",
    ),
    PidSpec(
        0x42,
        "control_voltage",
        "Control module voltage",
        "V",
        2,
        lambda d: _ab(d) / 1000.0,
        "control_module_voltage_v",
    ),
    PidSpec(
        0x46, "ambient_temp", "Ambient air temperature", "°C", 1, _temp, None, "ambient_temp_c"
    ),
    PidSpec(0x5C, "oil_temp", "Engine oil temperature", "°C", 1, _temp, "oil_temp_c"),
    PidSpec(
        0x5E, "fuel_rate", "Engine fuel rate", "L/h", 2, lambda d: _ab(d) / 20.0, "fuel_rate_lph"
    ),
)

PID_BY_NUMBER: Final = {spec.pid: spec for spec in DATA_PIDS}
SUPPORT_PIDS: Final = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0)
MONITOR_STATUS_PID: Final = 0x01
FREEZE_FRAME_DTC_PID: Final = 0x02

# TelemetrySample fields that generic OBD-II cannot provide on any vehicle.
NOT_AVAILABLE_OVER_OBD: Final = ("oil_pressure_kpa",)


def decode(spec: PidSpec, data: bytes) -> float:
    if len(data) < spec.length:
        raise ValueError(f"PID {spec.pid:02X} needs {spec.length} data bytes, got {len(data)}")
    return round(spec.decode(data[: spec.length]), 4)


@dataclass(frozen=True, slots=True)
class MonitorStatus:
    mil_on: bool
    dtc_count: int


def decode_monitor_status(data: bytes) -> MonitorStatus:
    if len(data) < 1:
        raise ValueError("PID 01 needs at least one data byte")
    return MonitorStatus(mil_on=bool(data[0] & 0x80), dtc_count=data[0] & 0x7F)
