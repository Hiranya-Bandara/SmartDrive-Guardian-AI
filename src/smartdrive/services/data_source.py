"""Common interface for telemetry sources (simulation now; live OBD-II and replay later)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from smartdrive.config.constants import DataSource
from smartdrive.models.telemetry import TelemetrySample

if TYPE_CHECKING:
    from smartdrive.services.scenarios import SimulationLabels


@dataclass(frozen=True, slots=True)
class TelemetryFrame:
    """One poll of a telemetry source.

    ``sample`` is ``None`` when the source did not respond (connection loss); individual
    sensors inside a sample may also be ``None`` when unsupported or not reported.
    """

    source: DataSource
    elapsed_s: float
    sample: TelemetrySample | None
    rejected: tuple[str, ...] = ()
    labels: SimulationLabels | None = field(default=None)

    @property
    def connected(self) -> bool:
        return self.sample is not None


class TelemetrySource(ABC):
    data_source: DataSource

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read(self, interval_s: float) -> TelemetryFrame:
        """Return the next frame. ``interval_s`` is the wall-clock time since the last read."""

    @abstractmethod
    def close(self) -> None: ...
