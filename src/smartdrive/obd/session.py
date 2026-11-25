"""Connection lifecycle for one adapter: connect, detect capabilities, poll, scan codes, close.

An :class:`ObdSession` is used from a single worker thread. It separates the adapter link from
the vehicle (ECU) link: an adapter can answer while the ignition is off, so ``connect`` reports
both. Reconnection is bounded by :class:`ReconnectPolicy`; the worker decides when to retry so
that waiting never blocks the user interface.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from smartdrive.config.constants import DtcStatus
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.obd.capabilities import VehicleCapabilities
from smartdrive.obd.discovery import COMMON_BAUD_RATES, validate_port_name
from smartdrive.obd.dtc import parse_codes
from smartdrive.obd.elm327 import AdapterInfo, Elm327Client, LinkQuality
from smartdrive.obd.errors import (
    AdapterNotRespondingError,
    CommunicationTimeoutError,
    EcuUnavailableError,
    MalformedResponseError,
    NoAdapterError,
    NoDataError,
    ObdError,
)
from smartdrive.obd.mock import MOCK_PORT, create_mock_transport
from smartdrive.obd.pids import PID_BY_NUMBER, MonitorStatus
from smartdrive.obd.responses import payload_for
from smartdrive.obd.telemetry_mapper import build_sample
from smartdrive.obd.transport import SerialTransport, Transport

logger = logging.getLogger(__name__)

BAUD_PROBE_LIMIT: Final = 4


class ConnectionStatus(StrEnum):
    DISCONNECTED = "disconnected"
    DISCOVERING = "discovering"
    CONNECTING = "connecting"
    ADAPTER_CONNECTED = "adapter_connected"
    ECU_CONNECTED = "ecu_connected"
    MONITORING = "monitoring"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    DISCONNECTING = "disconnecting"

    @property
    def label(self) -> str:
        return {
            "disconnected": "Disconnected",
            "discovering": "Searching for adapters",
            "connecting": "Connecting to adapter",
            "adapter_connected": "Adapter connected — vehicle not responding",
            "ecu_connected": "Vehicle ECU connected",
            "monitoring": "Polling the vehicle",
            "reconnecting": "Reconnecting",
            "failed": "Connection failed",
            "disconnecting": "Disconnecting",
        }[self.value]

    @property
    def has_adapter(self) -> bool:
        return self in (
            ConnectionStatus.ADAPTER_CONNECTED,
            ConnectionStatus.ECU_CONNECTED,
            ConnectionStatus.MONITORING,
        )

    @property
    def has_ecu(self) -> bool:
        return self in (ConnectionStatus.ECU_CONNECTED, ConnectionStatus.MONITORING)


@dataclass(frozen=True, slots=True)
class ConnectionParameters:
    port: str | None
    baudrate: int | None = None
    connect_timeout_s: float = 10.0
    query_timeout_s: float = 1.5
    mock_profile: str = "healthy"


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    max_attempts: int = 3
    initial_delay_s: float = 1.0
    max_delay_s: float = 15.0
    multiplier: float = 2.0

    def delay(self, attempt: int) -> float | None:
        """Delay before ``attempt`` (1-based), or ``None`` once attempts are exhausted."""
        if attempt < 1 or attempt > self.max_attempts:
            return None
        return min(self.max_delay_s, self.initial_delay_s * self.multiplier ** (attempt - 1))


@dataclass(frozen=True, slots=True)
class ConnectionReport:
    port: str
    transport_description: str
    is_mock: bool
    baudrate: int | None
    adapter: AdapterInfo
    connected_at: datetime
    ecu_connected: bool
    ecu_message: str | None = None
    protocol_number: str | None = None
    protocol_name: str | None = None
    capabilities: VehicleCapabilities | None = None
    monitor_status: MonitorStatus | None = None


@dataclass(frozen=True, slots=True)
class PollResult:
    timestamp: datetime
    sample: TelemetrySample | None
    unavailable: tuple[str, ...] = ()
    """Parameters the vehicle answered NO DATA for in this cycle."""
    malformed: tuple[str, ...] = ()
    timed_out: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class FreezeFrame:
    trigger_code: str | None
    values: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DtcScanResult:
    scanned_at: datetime
    stored: tuple[str, ...]
    pending: tuple[str, ...]
    permanent: tuple[str, ...] | None
    """``None`` when the vehicle does not support permanent-code reporting (mode 0A)."""
    mil_on: bool | None
    reported_count: int | None
    freeze_frame: FreezeFrame | None
    notes: tuple[str, ...] = ()

    def codes(self) -> list[tuple[str, DtcStatus]]:
        rows = [(c, DtcStatus.STORED) for c in self.stored]
        rows += [(c, DtcStatus.PENDING) for c in self.pending]
        rows += [(c, DtcStatus.PERMANENT) for c in self.permanent or ()]
        return rows


TransportFactory = Callable[[ConnectionParameters, int], Transport]


def default_transport_factory(params: ConnectionParameters, baudrate: int) -> Transport:
    if params.port == MOCK_PORT:
        return create_mock_transport(params.mock_profile)
    if params.port is None:
        raise NoAdapterError("No port selected")
    return SerialTransport(params.port, baudrate)


StatusCallback = Callable[[ConnectionStatus, str], None]


class ObdSession:
    def __init__(
        self,
        params: ConnectionParameters,
        *,
        transport_factory: TransportFactory = default_transport_factory,
        cancel: threading.Event | None = None,
        on_status: StatusCallback | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.params = params
        self._factory = transport_factory
        self._cancel = cancel or threading.Event()
        self._on_status = on_status
        self._clock = clock
        self._client: Elm327Client | None = None
        self._status = ConnectionStatus.DISCONNECTED
        self.report: ConnectionReport | None = None

    @property
    def status(self) -> ConnectionStatus:
        return self._status

    @property
    def client(self) -> Elm327Client | None:
        return self._client

    @property
    def is_mock(self) -> bool:
        return self._client is not None and self._client.transport.is_mock

    def quality(self) -> LinkQuality | None:
        return None if self._client is None else self._client.quality()

    def set_status(self, status: ConnectionStatus, message: str = "") -> None:
        self._status = status
        if self._on_status is not None:
            self._on_status(status, message)

    # -- connect --------------------------------------------------------------------------------

    def connect(self) -> ConnectionReport:
        if not self.params.port:
            raise NoAdapterError("No port selected")
        port = validate_port_name(self.params.port)
        self.set_status(ConnectionStatus.CONNECTING, f"Opening {port}")
        try:
            client, baudrate, info = self._open_adapter(port)
        except ObdError:
            self.set_status(ConnectionStatus.FAILED)
            raise
        self._client = client
        self.set_status(ConnectionStatus.ADAPTER_CONNECTED, info.version)
        report = ConnectionReport(
            port=port,
            transport_description=client.transport.description,
            is_mock=client.transport.is_mock,
            baudrate=baudrate,
            adapter=info,
            connected_at=self._clock(),
            ecu_connected=False,
        )
        self.report = self._connect_ecu(report)
        return self.report

    def _open_adapter(self, port: str) -> tuple[Elm327Client, int | None, AdapterInfo]:
        rates: tuple[int, ...]
        if port == MOCK_PORT:
            rates = (38400,)
        elif self.params.baudrate:
            rates = (self.params.baudrate,)
        else:
            rates = COMMON_BAUD_RATES[:BAUD_PROBE_LIMIT]
        last_error: ObdError | None = None
        for rate in rates:
            transport = self._factory(self.params, rate)
            transport.open()  # invalid port / port in use propagate immediately
            client = Elm327Client(
                transport,
                command_timeout_s=self.params.query_timeout_s,
                init_timeout_s=min(self.params.connect_timeout_s, 5.0),
                cancel=self._cancel,
            )
            try:
                info = client.initialize()
            except (AdapterNotRespondingError, CommunicationTimeoutError) as exc:
                last_error = exc
                transport.close()
                logger.info("No ELM327 reply", extra={"port": port, "baudrate": rate})
                continue
            except ObdError:
                transport.close()
                raise
            return client, (None if port == MOCK_PORT else rate), info
        raise AdapterNotRespondingError(f"No ELM327 reply on {port} at {rates}") from last_error

    def _connect_ecu(self, report: ConnectionReport) -> ConnectionReport:
        client = self._require_client()
        try:
            supported = client.supported_pids(timeout_s=self.params.connect_timeout_s)
        except (EcuUnavailableError, NoDataError, CommunicationTimeoutError) as exc:
            message = getattr(exc, "user_message", str(exc))
            self.set_status(ConnectionStatus.ADAPTER_CONNECTED, message)
            return _replace(report, ecu_connected=False, ecu_message=message)
        protocol = client.detect_protocol()
        monitor: MonitorStatus | None
        try:
            monitor = client.monitor_status()
        except (NoDataError, MalformedResponseError):
            monitor = None
        self.set_status(ConnectionStatus.ECU_CONNECTED, client.protocol_name or "")
        return _replace(
            report,
            ecu_connected=True,
            ecu_message=None,
            protocol_number=protocol,
            protocol_name=client.protocol_name,
            capabilities=VehicleCapabilities(frozenset(supported)),
            monitor_status=monitor,
        )

    def retry_ecu(self) -> ConnectionReport:
        if self.report is None:
            return self.connect()
        self.report = self._connect_ecu(self.report)
        return self.report

    def reconnect(self) -> ConnectionReport:
        """One reconnect attempt: close the transport and connect again."""
        self._close_transport()
        self.set_status(ConnectionStatus.RECONNECTING)
        return self.connect()

    # -- reading --------------------------------------------------------------------------------

    def poll(self) -> PollResult:
        """Read every supported parameter once. Raises only when the link itself has failed."""
        client = self._require_client()
        capabilities = self._require_capabilities()
        started = self._clock()
        readings: dict[int, float] = {}
        unavailable: list[str] = []
        malformed: list[str] = []
        timed_out: list[str] = []
        for spec in capabilities.pollable:
            try:
                readings[spec.pid] = client.read_pid(spec)
            except NoDataError:
                unavailable.append(spec.key)
            except MalformedResponseError:
                malformed.append(spec.key)
            except CommunicationTimeoutError:
                timed_out.append(spec.key)
        if capabilities.pollable and len(timed_out) == len(capabilities.pollable):
            raise CommunicationTimeoutError("Every parameter timed out in this polling cycle")
        timestamp = self._clock()
        sample, rejected = (None, ()) if not readings else build_sample(timestamp, readings)
        return PollResult(
            timestamp=timestamp,
            sample=sample,
            unavailable=tuple(unavailable),
            malformed=tuple(malformed),
            timed_out=tuple(timed_out),
            rejected=rejected,
            duration_ms=(timestamp - started).total_seconds() * 1000.0,
        )

    def scan_trouble_codes(self, *, include_freeze_frame: bool = True) -> DtcScanResult:
        client = self._require_client()
        if not self._status.has_ecu:
            raise EcuUnavailableError("The vehicle ECU is not connected")
        notes: list[str] = []
        monitor: MonitorStatus | None
        try:
            monitor = client.monitor_status()
        except (NoDataError, MalformedResponseError):
            monitor = None
            notes.append("The vehicle did not report MIL status (PID 01).")
        stored = tuple(client.trouble_codes(DtcStatus.STORED))
        pending = tuple(client.trouble_codes(DtcStatus.PENDING))
        permanent: tuple[str, ...] | None
        try:
            permanent = tuple(self._permanent(client))
        except NoDataError:
            permanent = None
            notes.append("Permanent trouble codes (mode 0A) are not supported by this vehicle.")
        freeze = self._freeze_frame(client) if include_freeze_frame else None
        if freeze is None and stored:
            notes.append("No freeze-frame data was available.")
        return DtcScanResult(
            scanned_at=self._clock(),
            stored=stored,
            pending=pending,
            permanent=permanent,
            mil_on=None if monitor is None else monitor.mil_on,
            reported_count=None if monitor is None else monitor.dtc_count,
            freeze_frame=freeze,
            notes=tuple(notes),
        )

    @staticmethod
    def _permanent(client: Elm327Client) -> list[str]:
        messages = client.messages("0A", timeout_s=max(client.command_timeout_s, 3.0))
        return parse_codes(payload_for(messages, bytes([0x4A])), is_can=client.is_can)

    def _freeze_frame(self, client: Elm327Client) -> FreezeFrame | None:
        try:
            trigger = client.freeze_frame_code()
        except (NoDataError, MalformedResponseError):
            return None
        if trigger is None:
            return None
        values: dict[str, float] = {}
        capabilities = self.report.capabilities if self.report else None
        for spec in capabilities.pollable if capabilities else ():
            try:
                values[spec.key] = client.freeze_frame_value(spec)
            except (NoDataError, MalformedResponseError):
                continue
        return FreezeFrame(trigger_code=trigger, values=values)

    # -- shutdown -------------------------------------------------------------------------------

    def close(self) -> None:
        if self._client is None:
            self.set_status(ConnectionStatus.DISCONNECTED)
            return
        self.set_status(ConnectionStatus.DISCONNECTING)
        if not self._cancel.is_set() and self._client.transport.is_open:
            self._client.close_protocol()
        self._close_transport()
        self.report = None
        self.set_status(ConnectionStatus.DISCONNECTED)

    def _close_transport(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.transport.close()

    def _require_client(self) -> Elm327Client:
        if self._client is None:
            raise NoAdapterError("Not connected to an adapter")
        return self._client

    def _require_capabilities(self) -> VehicleCapabilities:
        if self.report is None or self.report.capabilities is None:
            raise EcuUnavailableError("The vehicle ECU is not connected")
        return self.report.capabilities


def _replace(report: ConnectionReport, **changes: object) -> ConnectionReport:
    return replace(report, **changes)  # type: ignore[arg-type]


def describe_pid(pid: int) -> str:
    spec = PID_BY_NUMBER.get(pid)
    return spec.label if spec else f"PID {pid:02X}"
