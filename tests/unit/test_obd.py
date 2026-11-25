"""Read-only OBD-II layer: allowlist, parsing, ELM327 client and connection session.

All tests use the deterministic mock adapter or fake serial objects. None of them involves real
hardware, and they do not demonstrate compatibility with any physical adapter or vehicle.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from smartdrive.config.constants import DtcStatus
from smartdrive.obd import commands, discovery
from smartdrive.obd.capabilities import VehicleCapabilities
from smartdrive.obd.commands import ALLOWED_COMMANDS, PROHIBITED_EXAMPLES, validate
from smartdrive.obd.dtc import CodeCategory, category_of, decode_dtc, parse_codes
from smartdrive.obd.elm327 import Elm327Client
from smartdrive.obd.errors import (
    AdapterDisconnectedError,
    AdapterNotRespondingError,
    AdapterReportedError,
    CommunicationTimeoutError,
    EcuUnavailableError,
    InvalidPortError,
    MalformedResponseError,
    NoAdapterError,
    NoDataError,
    OperationCancelledError,
    PortInUseError,
    ProhibitedCommandError,
    UnsupportedProtocolError,
)
from smartdrive.obd.mock import (
    MOCK_PORT,
    PROFILES,
    MockElm327Transport,
    MockVehicleProfile,
    encode_code,
)
from smartdrive.obd.pids import DATA_PIDS, PID_BY_NUMBER, decode
from smartdrive.obd.responses import parse_messages
from smartdrive.obd.session import (
    ConnectionParameters,
    ConnectionStatus,
    ObdSession,
    ReconnectPolicy,
)
from smartdrive.obd.telemetry_mapper import build_sample
from smartdrive.obd.transport import SerialTransport, classify_serial_error

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def session_for(transport: MockElm327Transport, **params: Any) -> ObdSession:
    statuses: list[ConnectionStatus] = []
    session = ObdSession(
        ConnectionParameters(port=MOCK_PORT, **params),
        transport_factory=lambda _p, _b: transport,
        on_status=lambda status, _msg: statuses.append(status),
        clock=lambda: NOW,
    )
    session.statuses = statuses  # type: ignore[attr-defined]
    return session


# -- allowlist ---------------------------------------------------------------------------------


class TestReadOnlyAllowlist:
    @pytest.mark.parametrize("request_text", PROHIBITED_EXAMPLES)
    def test_known_write_and_control_commands_are_rejected(self, request_text: str) -> None:
        with pytest.raises(ProhibitedCommandError):
            validate(request_text)

    @pytest.mark.parametrize(
        "request_text",
        ["010C\r04", "010C\n", "03;04", "", "AT Z\x00", "01 0C 04", "0", "ATSH 7E0", 42],
    )
    def test_injection_and_malformed_requests_are_rejected(self, request_text: Any) -> None:
        with pytest.raises(ProhibitedCommandError):
            validate(request_text)

    def test_spacing_and_case_are_normalised(self) -> None:
        assert validate("01 0c").request == "010C"
        assert validate("at z").request == "ATZ"

    def test_allowlist_contains_only_read_modes(self) -> None:
        for request, command in ALLOWED_COMMANDS.items():
            assert request == command.request
            if not request.startswith("AT"):
                assert request[:2] in {"01", "02", "03", "07", "0A"}, request
        assert {"03", "07", "0A"} <= set(ALLOWED_COMMANDS)
        assert not any(r.startswith(("04", "08", "09")) for r in ALLOWED_COMMANDS)

    def test_every_polled_pid_is_allowed(self) -> None:
        for spec in DATA_PIDS:
            assert commands.is_allowed(spec.request)

    def test_prohibited_command_never_reaches_the_transport(self) -> None:
        transport = MockElm327Transport()
        transport.open()
        client = Elm327Client(transport)
        for request_text in PROHIBITED_EXAMPLES:
            with pytest.raises(ProhibitedCommandError):
                client.send(request_text)
            with pytest.raises(ProhibitedCommandError):
                client.messages(request_text)
        assert transport.requests == []


# -- decoding ----------------------------------------------------------------------------------


class TestDecoding:
    @pytest.mark.parametrize(
        ("pid", "data", "expected"),
        [
            (0x0C, bytes([0x1A, 0xF8]), 1726.0),
            (0x05, bytes([0x7B]), 83.0),
            (0x0D, bytes([0x3C]), 60.0),
            (0x04, bytes([0xFF]), 100.0),
            (0x42, bytes([0x37, 0x1A]), 14.106),
            (0x06, bytes([0x80]), 0.0),
            (0x10, bytes([0x01, 0x90]), 4.0),
            (0x5E, bytes([0x00, 0x50]), 4.0),
        ],
    )
    def test_j1979_formulas(self, pid: int, data: bytes, expected: float) -> None:
        assert decode(PID_BY_NUMBER[pid], data) == pytest.approx(expected)

    def test_short_data_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="needs 2 data bytes"):
            decode(PID_BY_NUMBER[0x0C], bytes([0x1A]))

    @pytest.mark.parametrize(
        ("first", "second", "code"),
        [
            (0x01, 0x33, "P0133"),
            (0x43, 0x00, "C0300"),
            (0x81, 0x01, "B0101"),
            (0xC1, 0x00, "U0100"),
        ],
    )
    def test_dtc_bytes(self, first: int, second: int, code: str) -> None:
        assert decode_dtc(first, second) == code
        assert encode_code(code) == bytes([first, second])

    def test_categories(self) -> None:
        assert category_of("U0100") is CodeCategory.NETWORK
        assert CodeCategory.CHASSIS.label == "Chassis"

    def test_can_codes_use_count_byte_and_legacy_codes_skip_padding(self) -> None:
        assert parse_codes([bytes([0x02, 0x01, 0x33, 0x01, 0x71])], is_can=True) == [
            "P0133",
            "P0171",
        ]
        assert parse_codes([bytes([0x01, 0x33, 0x00, 0x00, 0x00, 0x00])], is_can=False) == ["P0133"]
        with pytest.raises(MalformedResponseError):
            parse_codes([bytes([0x03, 0x01, 0x33])], is_can=True)

    def test_multi_frame_reply_is_reassembled(self) -> None:
        raw = "00E\r0: 43 05 03 01 01 71\r1: 04 20 04 42 01 18 00\r2: 00 00 00 00 00 00 00\r\r>"
        (message,) = parse_messages(raw)
        assert message[0] == 0x43
        assert parse_codes([message[1:]], is_can=True) == [
            "P0301",
            "P0171",
            "P0420",
            "P0442",
            "P0118",
        ]

    def test_status_words(self) -> None:
        with pytest.raises(NoDataError):
            parse_messages("NO DATA\r\r>")
        with pytest.raises(UnsupportedProtocolError):
            parse_messages("SEARCHING...\rUNABLE TO CONNECT\r\r>")
        with pytest.raises(AdapterReportedError):
            parse_messages("CAN ERROR\r\r>")
        with pytest.raises(MalformedResponseError):
            parse_messages("41 0C ZZ\r>")
        # One ECU without data does not hide the one that answered.
        assert parse_messages("NO DATA\r41 0D 3C\r>") == [bytes([0x41, 0x0D, 0x3C])]

    def test_out_of_range_values_are_dropped_not_clamped(self) -> None:
        sample, rejected = build_sample(NOW, {0x0C: 2000.0, 0x05: 300.0, 0x10: 5.0})
        assert sample.rpm == 2000.0
        assert sample.coolant_temp_c is None
        assert rejected == ("coolant_temp_c",)
        assert sample.extra == {"maf_gps": 5.0}


# -- client and session ------------------------------------------------------------------------


class TestSession:
    def test_successful_connection_reports_adapter_ecu_and_capabilities(self) -> None:
        transport = MockElm327Transport()
        session = session_for(transport)
        report = session.connect()
        assert report.is_mock and report.ecu_connected
        assert "MOCK" in report.adapter.version
        assert report.adapter.device_description is not None
        assert "NOT REAL HARDWARE" in report.adapter.device_description
        assert report.protocol_name == "ISO 15765-4 CAN (11-bit, 500 kbaud)"
        assert report.capabilities is not None
        assert {s.pid for s in report.capabilities.pollable} == set(
            transport.profile.supported_pids
        )
        assert report.monitor_status is not None and not report.monitor_status.mil_on
        assert session.status is ConnectionStatus.ECU_CONNECTED
        assert session.statuses[:2] == [  # type: ignore[attr-defined]
            ConnectionStatus.CONNECTING,
            ConnectionStatus.ADAPTER_CONNECTED,
        ]
        assert all(commands.is_allowed(r) for r in transport.requests)

    def test_ecu_failure_keeps_adapter_connected(self) -> None:
        session = session_for(MockElm327Transport(PROFILES["no_ecu"]()))
        report = session.connect()
        assert not report.ecu_connected
        assert report.ecu_message and "ignition" in report.ecu_message.lower()
        assert session.status is ConnectionStatus.ADAPTER_CONNECTED
        with pytest.raises(EcuUnavailableError):
            session.poll()

    def test_device_that_is_not_an_elm327(self) -> None:
        profile = MockVehicleProfile(adapter_responds=False)
        session = session_for(MockElm327Transport(profile))
        with pytest.raises(AdapterNotRespondingError):
            session.connect()
        assert session.status is ConnectionStatus.FAILED

    def test_missing_port_and_invalid_port(self) -> None:
        with pytest.raises(NoAdapterError):
            ObdSession(ConnectionParameters(port=None)).connect()
        with pytest.raises(ValueError, match="not a serial port name"):
            ObdSession(ConnectionParameters(port="http://example")).connect()
        session = session_for(MockElm327Transport(exists=False))
        with pytest.raises(InvalidPortError):
            session.connect()

    def test_polling_reads_values_and_marks_missing_sensors(self) -> None:
        clock = FakeClock()
        transport = MockElm327Transport(PROFILES["partial_sensors"](), clock=clock)
        session = session_for(transport)
        session.connect()
        clock.t = 20.0
        result = session.poll()
        assert result.sample is not None
        assert result.sample.rpm is not None and result.sample.coolant_temp_c == 61.0
        assert result.sample.fuel_level_pct is None  # unsupported: missing, not zero
        assert result.sample.oil_pressure_kpa is None
        capabilities = session.report.capabilities  # type: ignore[union-attr]
        assert capabilities is not None
        assert "oil_pressure_kpa" in capabilities.missing_sample_fields
        assert any("not defined in generic OBD-II" in n for n in capabilities.describe_missing())

    def test_malformed_and_silent_parameters_do_not_break_the_cycle(self) -> None:
        profile = MockVehicleProfile(
            malformed_pids=frozenset({0x0D}), silent_pids=frozenset({0x05})
        )
        session = session_for(MockElm327Transport(profile))
        session.connect()
        result = session.poll()
        assert result.sample is not None
        assert result.sample.speed_kph is None and result.sample.coolant_temp_c is None
        assert result.malformed == ("speed_kph",)
        assert result.timed_out == ("coolant_temp_c",)
        quality = session.quality()
        assert quality is not None and quality.timeouts >= 1 and quality.failures >= 2

    def test_every_parameter_timing_out_is_a_link_failure(self) -> None:
        profile = MockVehicleProfile(
            supported_pids=frozenset({0x05, 0x0C}), silent_pids=frozenset({0x05, 0x0C})
        )
        session = session_for(MockElm327Transport(profile))
        session.connect()
        with pytest.raises(CommunicationTimeoutError):
            session.poll()

    def test_disconnection_and_bounded_reconnection(self) -> None:
        profile = MockVehicleProfile(disconnect_after=6)
        transport = MockElm327Transport(profile)
        session = session_for(transport)
        session.connect()
        with pytest.raises(AdapterDisconnectedError):
            for _ in range(5):
                session.poll()
        profile.disconnect_after = None
        report = session.reconnect()
        assert report.ecu_connected and transport.open_count == 2
        assert ConnectionStatus.RECONNECTING in session.statuses  # type: ignore[attr-defined]

    def test_unplugged_adapter_that_does_not_return(self) -> None:
        transport = MockElm327Transport(MockVehicleProfile(reconnectable=False))
        session = session_for(transport)
        session.connect()
        transport.unplug()
        with pytest.raises(AdapterDisconnectedError):
            session.poll()
        with pytest.raises(AdapterDisconnectedError):
            session.reconnect()

    def test_reconnect_policy_is_bounded_with_backoff(self) -> None:
        policy = ReconnectPolicy(max_attempts=4, initial_delay_s=1.0, max_delay_s=5.0)
        assert [policy.delay(n) for n in range(1, 6)] == [1.0, 2.0, 4.0, 5.0, None]
        assert ReconnectPolicy(max_attempts=0).delay(1) is None

    def test_cancellation_interrupts_a_pending_read(self) -> None:
        cancel = threading.Event()
        transport = MockElm327Transport()
        session = ObdSession(
            ConnectionParameters(port=MOCK_PORT),
            transport_factory=lambda _p, _b: transport,
            cancel=cancel,
        )
        session.connect()
        cancel.set()
        with pytest.raises(OperationCancelledError):
            session.poll()
        session.close()
        assert session.status is ConnectionStatus.DISCONNECTED
        assert not transport.is_open

    def test_close_releases_the_port(self) -> None:
        transport = MockElm327Transport()
        session = session_for(transport)
        session.connect()
        session.close()
        assert not transport.is_open
        assert transport.requests[-1] == "ATPC"
        assert session.report is None


class TestTroubleCodes:
    def test_stored_pending_permanent_and_freeze_frame(self) -> None:
        session = session_for(MockElm327Transport(PROFILES["stored_codes"]()))
        session.connect()
        scan = session.scan_trouble_codes()
        assert scan.stored == ("P0301", "P0171")
        assert scan.pending == ("P0420",)
        assert scan.permanent == ("P0301",)
        assert scan.mil_on is True and scan.reported_count == 2
        assert scan.freeze_frame is not None
        assert scan.freeze_frame.trigger_code == "P0301"
        assert scan.freeze_frame.values["rpm"] == 2150.0
        assert scan.freeze_frame.values["coolant_temp_c"] == 88.0
        assert (("P0420", DtcStatus.PENDING)) in scan.codes()

    def test_legacy_protocol_without_count_byte(self) -> None:
        session = session_for(MockElm327Transport(PROFILES["legacy_protocol"]()))
        report = session.connect()
        assert report.protocol_name == "ISO 9141-2"
        scan = session.scan_trouble_codes(include_freeze_frame=False)
        assert scan.stored == ("P0133", "P0442", "P0118", "P0507")
        assert scan.pending == ()

    def test_empty_response_and_unsupported_permanent_codes(self) -> None:
        session = session_for(MockElm327Transport(PROFILES["partial_sensors"]()))
        session.connect()
        scan = session.scan_trouble_codes()
        assert scan.stored == () and scan.pending == ()
        assert scan.permanent is None
        assert any("Permanent" in note for note in scan.notes)
        assert scan.freeze_frame is None

    def test_scan_requires_the_ecu(self) -> None:
        session = session_for(MockElm327Transport(PROFILES["no_ecu"]()))
        session.connect()
        with pytest.raises(EcuUnavailableError):
            session.scan_trouble_codes()

    def test_scan_sends_no_clearing_command(self) -> None:
        transport = MockElm327Transport(PROFILES["stored_codes"]())
        session = session_for(transport)
        session.connect()
        session.scan_trouble_codes()
        assert not any(r.startswith("04") for r in transport.requests)
        assert all(commands.is_allowed(r) for r in transport.requests)


# -- discovery and serial transport -----------------------------------------------------------


class FakePort:
    def __init__(self, device: str, description: str, hwid: str = "n/a") -> None:
        self.device = device
        self.description = description
        self.hwid = hwid
        self.manufacturer = None


class TestDiscovery:
    def test_ports_are_listed_without_opening_them(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [
                FakePort("COM10", "Standard Serial over Bluetooth link", "BTHENUM\\{1101}"),
                FakePort("COM3", "USB-SERIAL CH340", "USB VID:PID=1A86:7523"),
            ],
        )
        ports = discovery.list_serial_ports()
        assert [p.port for p in ports] == ["COM3", "COM10"]
        assert ports[0].connection_method == "USB serial"
        assert ports[1].connection_method == "Bluetooth Classic (serial port)"
        assert all(not p.is_mock for p in ports)
        with_mock = discovery.list_serial_ports(include_mock=True)
        assert with_mock[-1].is_mock and "not a vehicle" in with_mock[-1].description

    def test_port_name_validation(self) -> None:
        assert discovery.validate_port_name(" com7 ") == "COM7"
        assert discovery.validate_port_name("mock") == MOCK_PORT
        for bad in ("COM0", "COM", "LPT1", "../../etc/passwd", "COM3; rm"):
            with pytest.raises(ValueError):
                discovery.validate_port_name(bad)

    def test_serial_open_errors_are_classified(self) -> None:
        assert isinstance(
            classify_serial_error("COM3", OSError("PermissionError(13, 'Access is denied.')")),
            PortInUseError,
        )
        assert isinstance(
            classify_serial_error("COM9", OSError("FileNotFoundError: The system cannot find")),
            InvalidPortError,
        )
        assert isinstance(classify_serial_error("COM9", OSError("weird")), AdapterDisconnectedError)

    def test_serial_transport_reads_until_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import serial

        class FakeSerial:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.is_open = True
                self.written: list[bytes] = []
                self.chunks = [b"41 0C ", b"1A F8\r\r>"]

            def write(self, data: bytes) -> None:
                self.written.append(data)

            def flush(self) -> None:
                pass

            def read(self, _size: int) -> bytes:
                return self.chunks.pop(0) if self.chunks else b""

            def reset_input_buffer(self) -> None:
                pass

            def close(self) -> None:
                self.is_open = False

        monkeypatch.setattr(serial, "Serial", FakeSerial)
        transport = SerialTransport("COM3", 38400)
        transport.open()
        transport.write(b"010C\r")
        assert transport.read_until_prompt(1.0).startswith("41 0C 1A F8")
        with pytest.raises(CommunicationTimeoutError):
            transport.read_until_prompt(0.1)
        transport.close()
        assert not transport.is_open

    def test_serial_open_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import serial

        def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise serial.SerialException("could not open port 'COM4': PermissionError(13)")

        monkeypatch.setattr(serial, "Serial", refuse)
        with pytest.raises(PortInUseError):
            SerialTransport("COM4", 38400).open()


def test_capabilities_order_is_stable() -> None:
    capabilities = VehicleCapabilities(frozenset({0x0D, 0x0C, 0x05}))
    assert [s.pid for s in capabilities.pollable] == [0x05, 0x0C, 0x0D]
    assert capabilities.sensor_count == 3
