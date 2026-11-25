"""Local trouble-code reference.

Descriptions cover a curated set of *generic* codes. They are SmartDrive's own short paraphrases
of the publicly known SAE J2012 generic definitions, not a copy of the standard, and the wording
of the standard itself may differ. Manufacturer-specific codes (for example P1xxx, B1xxx, U1xxx)
are never given a meaning here: their definitions belong to each manufacturer, so the reference
reports them as unknown and only explains the code structure.

A trouble code records that a control unit detected a condition. It does not confirm that a
particular component has failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from smartdrive.obd.dtc import CodeCategory, category_of, is_valid_code

REFERENCE_SOURCE: Final = (
    "SmartDrive local reference — paraphrased generic (SAE J2012) definitions; verify with "
    "the vehicle's service information"
)
UNKNOWN_SOURCE: Final = "No description in the local reference"

_GENERIC: Final[dict[str, str]] = {
    "P0010": "Camshaft position actuator 'A' circuit (bank 1)",
    "P0011": "Camshaft position 'A' timing over-advanced or system performance (bank 1)",
    "P0012": "Camshaft position 'A' timing over-retarded (bank 1)",
    "P0016": "Crankshaft position / camshaft position correlation (bank 1, sensor A)",
    "P0087": "Fuel rail / system pressure too low",
    "P0088": "Fuel rail / system pressure too high",
    "P0100": "Mass or volume air flow sensor circuit",
    "P0101": "Mass or volume air flow sensor circuit range/performance",
    "P0102": "Mass or volume air flow sensor circuit low",
    "P0103": "Mass or volume air flow sensor circuit high",
    "P0105": "Manifold absolute pressure / barometric pressure sensor circuit",
    "P0106": "Manifold absolute pressure / barometric pressure sensor range/performance",
    "P0107": "Manifold absolute pressure / barometric pressure sensor circuit low",
    "P0108": "Manifold absolute pressure / barometric pressure sensor circuit high",
    "P0110": "Intake air temperature sensor circuit",
    "P0112": "Intake air temperature sensor circuit low",
    "P0113": "Intake air temperature sensor circuit high",
    "P0115": "Engine coolant temperature sensor circuit",
    "P0116": "Engine coolant temperature sensor circuit range/performance",
    "P0117": "Engine coolant temperature sensor circuit low",
    "P0118": "Engine coolant temperature sensor circuit high",
    "P0120": "Throttle/pedal position sensor 'A' circuit",
    "P0121": "Throttle/pedal position sensor 'A' circuit range/performance",
    "P0122": "Throttle/pedal position sensor 'A' circuit low",
    "P0123": "Throttle/pedal position sensor 'A' circuit high",
    "P0125": "Insufficient coolant temperature for closed-loop fuel control",
    "P0128": "Coolant temperature below thermostat regulating temperature",
    "P0130": "Oxygen sensor circuit (bank 1, sensor 1)",
    "P0131": "Oxygen sensor circuit low voltage (bank 1, sensor 1)",
    "P0132": "Oxygen sensor circuit high voltage (bank 1, sensor 1)",
    "P0133": "Oxygen sensor circuit slow response (bank 1, sensor 1)",
    "P0134": "Oxygen sensor circuit no activity detected (bank 1, sensor 1)",
    "P0135": "Oxygen sensor heater circuit (bank 1, sensor 1)",
    "P0136": "Oxygen sensor circuit (bank 1, sensor 2)",
    "P0137": "Oxygen sensor circuit low voltage (bank 1, sensor 2)",
    "P0138": "Oxygen sensor circuit high voltage (bank 1, sensor 2)",
    "P0140": "Oxygen sensor circuit no activity detected (bank 1, sensor 2)",
    "P0141": "Oxygen sensor heater circuit (bank 1, sensor 2)",
    "P0171": "System too lean (bank 1)",
    "P0172": "System too rich (bank 1)",
    "P0174": "System too lean (bank 2)",
    "P0175": "System too rich (bank 2)",
    "P0190": "Fuel rail pressure sensor circuit",
    "P0200": "Injector circuit",
    "P0201": "Injector circuit — cylinder 1",
    "P0202": "Injector circuit — cylinder 2",
    "P0203": "Injector circuit — cylinder 3",
    "P0204": "Injector circuit — cylinder 4",
    "P0217": "Engine coolant over-temperature condition",
    "P0218": "Transmission fluid over-temperature condition",
    "P0219": "Engine over-speed condition",
    "P0234": "Turbocharger/supercharger 'A' overboost condition",
    "P0299": "Turbocharger/supercharger 'A' underboost condition",
    "P0300": "Random or multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0305": "Cylinder 5 misfire detected",
    "P0306": "Cylinder 6 misfire detected",
    "P0325": "Knock sensor 1 circuit (bank 1 or single sensor)",
    "P0335": "Crankshaft position sensor 'A' circuit",
    "P0336": "Crankshaft position sensor 'A' circuit range/performance",
    "P0340": "Camshaft position sensor 'A' circuit (bank 1 or single sensor)",
    "P0341": "Camshaft position sensor 'A' circuit range/performance (bank 1)",
    "P0351": "Ignition coil 'A' primary/secondary circuit",
    "P0352": "Ignition coil 'B' primary/secondary circuit",
    "P0353": "Ignition coil 'C' primary/secondary circuit",
    "P0354": "Ignition coil 'D' primary/secondary circuit",
    "P0400": "Exhaust gas recirculation 'A' flow",
    "P0401": "Exhaust gas recirculation 'A' flow insufficient",
    "P0402": "Exhaust gas recirculation 'A' flow excessive",
    "P0420": "Catalyst system efficiency below threshold (bank 1)",
    "P0430": "Catalyst system efficiency below threshold (bank 2)",
    "P0440": "Evaporative emission system",
    "P0441": "Evaporative emission system incorrect purge flow",
    "P0442": "Evaporative emission system leak detected (small leak)",
    "P0443": "Evaporative emission system purge control valve circuit",
    "P0446": "Evaporative emission system vent control circuit",
    "P0455": "Evaporative emission system leak detected (large leak)",
    "P0456": "Evaporative emission system leak detected (very small leak)",
    "P0457": "Evaporative emission system leak detected (fuel cap loose or off)",
    "P0461": "Fuel level sensor 'A' circuit range/performance",
    "P0462": "Fuel level sensor 'A' circuit low",
    "P0463": "Fuel level sensor 'A' circuit high",
    "P0480": "Cooling fan 1 control circuit",
    "P0500": "Vehicle speed sensor 'A'",
    "P0505": "Idle air control system",
    "P0506": "Idle control system — engine speed lower than expected",
    "P0507": "Idle control system — engine speed higher than expected",
    "P0520": "Engine oil pressure sensor/switch circuit",
    "P0521": "Engine oil pressure sensor/switch range/performance",
    "P0522": "Engine oil pressure sensor/switch circuit low",
    "P0523": "Engine oil pressure sensor/switch circuit high",
    "P0524": "Engine oil pressure too low",
    "P0560": "System voltage",
    "P0562": "System voltage low",
    "P0563": "System voltage high",
    "P0600": "Serial communication link",
    "P0601": "Internal control module memory checksum error",
    "P0603": "Internal control module keep-alive memory error",
    "P0604": "Internal control module random access memory error",
    "P0605": "Internal control module read-only memory error",
    "P0606": "Control module processor",
    "P0700": "Transmission control system (malfunction indicator request)",
    "P0705": "Transmission range sensor 'A' circuit",
    "P0715": "Input/turbine speed sensor 'A' circuit",
    "P0720": "Output speed sensor circuit",
    "P0730": "Incorrect gear ratio",
    "P0740": "Torque converter clutch solenoid circuit/open",
    "P0741": "Torque converter clutch solenoid circuit performance or stuck off",
    "P0750": "Shift solenoid 'A'",
    "P0755": "Shift solenoid 'B'",
    "P2096": "Post-catalyst fuel trim system too lean (bank 1)",
    "P2097": "Post-catalyst fuel trim system too rich (bank 1)",
    "P2135": "Throttle/pedal position sensor 'A'/'B' voltage correlation",
    "U0001": "High-speed CAN communication bus",
    "U0073": "Control module communication bus 'A' off",
    "U0100": "Lost communication with engine/powertrain control module 'A'",
    "U0101": "Lost communication with transmission control module",
    "U0121": "Lost communication with anti-lock brake system control module",
    "U0140": "Lost communication with body control module",
    "U0155": "Lost communication with instrument panel cluster control module",
}

_POWERTRAIN_SYSTEMS: Final = {
    "0": "Fuel and air metering, auxiliary emission controls",
    "1": "Fuel and air metering",
    "2": "Fuel and air metering (injector circuits)",
    "3": "Ignition system or misfire",
    "4": "Auxiliary emission controls",
    "5": "Vehicle speed, idle control and auxiliary inputs",
    "6": "Control module and output circuits",
    "7": "Transmission",
    "8": "Transmission",
    "9": "Transmission",
    "A": "Hybrid / electric propulsion",
    "B": "Hybrid / electric propulsion",
    "C": "Hybrid / electric propulsion",
}

_NEXT_STEPS: Final = {
    "3": (
        "Misfire and ignition codes can come with a flashing check-engine lamp, which signals a "
        "misfire severe enough to damage the catalytic converter. Avoid high engine load and "
        "have the ignition and fuel systems inspected by a qualified technician."
    ),
    "temperature": (
        "If the temperature gauge or SmartDrive shows high coolant temperature, stop when it is "
        "safe, switch the engine off and let it cool. Do not open a hot cooling system. Have the "
        "cooling system checked by a qualified technician."
    ),
    "oil": (
        "An oil-pressure warning can indicate a condition that damages the engine quickly. Stop "
        "when it is safe and have the vehicle inspected before driving further."
    ),
    "U": (
        "Network codes mean a control module stopped communicating. They can follow a flat "
        "battery or a jump start, but can also affect safety systems; have the vehicle checked."
    ),
    "default": (
        "Note the code and when it appeared, and have it diagnosed by a qualified technician "
        "using the vehicle's service information. A code alone does not identify a failed part."
    ),
}


@dataclass(frozen=True, slots=True)
class CodeInfo:
    code: str
    category: CodeCategory
    description: str | None
    source: str
    generic: bool
    system: str
    next_steps: str

    @property
    def known(self) -> bool:
        return self.description is not None

    @property
    def display_description(self) -> str:
        if self.description is not None:
            return self.description
        if not self.generic:
            return "Manufacturer-specific code — meaning not in the local reference"
        return "Unknown code — no description in the local reference"


def is_generic(code: str) -> bool:
    """Whether the code number lies in a range SAE defines for all manufacturers."""
    digit = code[1]
    if code[0] == "P":
        if digit in ("0", "2"):
            return True
        if digit == "3":
            return code[2] in "456789"
        return False
    return digit in ("0", "3")


def system_of(code: str) -> str:
    category = category_of(code)
    if category is CodeCategory.POWERTRAIN:
        return _POWERTRAIN_SYSTEMS.get(code[2], "Powertrain (unspecified subsystem)")
    return category.label


def next_steps_for(code: str) -> str:
    if code[0] == "U":
        return _NEXT_STEPS["U"]
    if code in ("P0217", "P0118", "P0116", "P0128"):
        return _NEXT_STEPS["temperature"]
    if code in ("P0520", "P0521", "P0522", "P0523", "P0524"):
        return _NEXT_STEPS["oil"]
    if code[0] == "P" and code[2] == "3":
        return _NEXT_STEPS["3"]
    return _NEXT_STEPS["default"]


def lookup(code: str) -> CodeInfo:
    normalised = code.strip().upper()
    if not is_valid_code(normalised):
        raise ValueError(f"{code!r} is not a valid trouble code")
    generic = is_generic(normalised)
    description = _GENERIC.get(normalised) if generic else None
    return CodeInfo(
        code=normalised,
        category=category_of(normalised),
        description=description,
        source=REFERENCE_SOURCE if description else UNKNOWN_SOURCE,
        generic=generic,
        system=system_of(normalised),
        next_steps=next_steps_for(normalised),
    )


def reference_size() -> int:
    return len(_GENERIC)
