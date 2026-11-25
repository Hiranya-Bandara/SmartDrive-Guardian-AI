"""Turns one polling cycle of decoded PIDs into a :class:`TelemetrySample`.

Values arrive already in SmartDrive's metric units. A PID that was not reported in this cycle
stays ``None``; a value outside the sample's physical bounds is dropped and listed as rejected,
never clamped or replaced.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from smartdrive.models.telemetry import TelemetrySample
from smartdrive.obd.pids import PID_BY_NUMBER


def build_sample(
    timestamp: datetime, readings: dict[int, float]
) -> tuple[TelemetrySample, tuple[str, ...]]:
    fields: dict[str, float] = {}
    extra: dict[str, float] = {}
    for pid, value in readings.items():
        spec = PID_BY_NUMBER[pid]
        if spec.sample_field is not None:
            fields[spec.sample_field] = value
        elif spec.extra_key is not None:
            extra[spec.extra_key] = value
    rejected: list[str] = []
    while True:
        try:
            sample = TelemetrySample(timestamp=timestamp, extra=extra, **fields)
        except ValidationError as exc:
            bad = {str(err["loc"][0]) for err in exc.errors() if err["loc"]}
            bad &= set(fields)
            if not bad:
                raise
            for name in sorted(bad):
                fields.pop(name)
                rejected.append(name)
            continue
        return sample, tuple(rejected)
