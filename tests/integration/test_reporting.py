"""PDF reports and CSV exports: real files, content, privacy, escaping and failure handling."""

from __future__ import annotations

import csv
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from smartdrive.config.constants import (
    DataSource,
    DiagnosticSource,
    FaultCategory,
    MaintenanceCategory,
    Severity,
)
from smartdrive.database.connection import Database
from smartdrive.database.models import DiagnosticResultRecord
from smartdrive.models.maintenance import MaintenanceRecordInput
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.obd.mock import MOCK_PORT, PROFILES, MockElm327Transport
from smartdrive.obd.session import ConnectionParameters, ObdSession
from smartdrive.reporting.csv_exporter import Column, format_cell, sanitise_text, write_csv
from smartdrive.reporting.document import ReportDocument
from smartdrive.reporting.pdf_generator import pdf_safe, render_pdf
from smartdrive.reporting.report_templates import ReportRequest, ReportType, group_findings
from smartdrive.services.maintenance_service import MaintenanceService
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.obd_service import ObdHistoryService
from smartdrive.services.report_service import CsvDataset, ReportService
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.trip_service import TripService
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.utils.exceptions import ExportError

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
PAGE = re.compile(rb"/Type /Page\b(?!s)")


def page_count(path: Path) -> int:
    return len(PAGE.findall(path.read_bytes()))


class World:
    def __init__(self, database: Database, tmp_path: Path, profile: VehicleProfile) -> None:
        self.db = database
        self.vehicle = VehicleService(database, tmp_path / "img").add(
            profile.model_copy(update={"notes": "Garage door code 4321"})
        )
        self.telemetry = TelemetryService(database)
        self.trips = TripService(database, self.telemetry)
        self.obd = ObdHistoryService(database)
        self.maintenance = MaintenanceService(database)
        self.service = ReportService(
            database,
            telemetry=self.telemetry,
            trips=self.trips,
            obd=self.obd,
            maintenance=self.maintenance,
            notifications=NotificationService(database),
            clock=lambda: datetime(2026, 11, 25, 9, 0, tzinfo=UTC),
        )
        self.trip_id = self._trip(findings=80)

    def _trip(self, *, findings: int) -> int:
        session = self.telemetry.start_session(
            self.vehicle.id, DataSource.SIMULATION, name="Test drive", started_at=T0
        )
        samples = [
            TelemetrySample(
                timestamp=T0 + timedelta(seconds=t),
                speed_kph=60.0 if t % 50 else None,
                rpm=2100.0,
                coolant_temp_c=90.0 + t / 30,
                control_module_voltage_v=14.1,
            )
            for t in range(600)
        ]
        self.telemetry.append(session.id, samples)
        self.telemetry.end_session(session.id)
        with self.db.session() as s:
            for index in range(findings):
                # Separate episodes (> 2 min apart) so the table spans several pages.
                s.add(
                    DiagnosticResultRecord(
                        vehicle_id=self.vehicle.id,
                        session_id=session.id,
                        created_at=T0 + timedelta(minutes=3 * index),
                        category=FaultCategory.COOLING,
                        severity=Severity.CRITICAL if index % 3 == 0 else Severity.WARNING,
                        source=DiagnosticSource.RULE,
                        summary=f"Coolant temperature high (episode {index})",
                        recommendation="Stop safely and let the engine cool.",
                        data_source=DataSource.SIMULATION,
                    )
                )
        self.trips.finalize(session.id)
        return session.id

    def scan(self) -> None:
        transport = MockElm327Transport(PROFILES["stored_codes"]())
        session = ObdSession(
            ConnectionParameters(port=MOCK_PORT), transport_factory=lambda _p, _b: transport
        )
        report = session.connect()
        result = session.scan_trouble_codes()
        session.close()
        self.obd.record_scan(
            self.vehicle.id,
            result,
            data_source=DataSource.SIMULATION,
            is_mock=True,
            protocol=report.protocol_name,
        )

    def service_record(self) -> None:
        self.maintenance.add_record(
            self.vehicle.id,
            MaintenanceRecordInput(
                category=MaintenanceCategory.ENGINE_OIL,
                title='=HYPERLINK("http://example.invalid")',
                service_date=date(2026, 6, 1),
                mileage_km=45_000,
                cost=Decimal("18500.00"),
                currency="LKR",
                provider='Garage, "Main" street',
                notes="Private maintenance note",
            ),
        )


@pytest.fixture
def world(database: Database, tmp_path: Path, vehicle_profile: VehicleProfile) -> World:
    return World(database, tmp_path, vehicle_profile)


class TestPdfReports:
    @pytest.mark.parametrize("kind", list(ReportType))
    def test_every_report_type_produces_a_real_pdf(
        self, world: World, tmp_path: Path, kind: ReportType
    ) -> None:
        world.scan()
        world.service_record()
        request = ReportRequest(
            kind,
            vehicle_id=None if kind is ReportType.MODEL_EVALUATION else world.vehicle.id,
            session_id=world.trip_id if kind is ReportType.TRIP else None,
        )
        path = tmp_path / f"{kind.value}.pdf"
        result = world.service.generate_pdf(request, path)
        data = path.read_bytes()
        assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
        assert result.size_bytes == len(data)
        assert page_count(path) >= 1
        # Metadata must not reveal where the file or its temporary copy was written.
        assert str(tmp_path).encode() not in data
        assert b".smartdrive-" not in data
        (history,) = world.service.history()
        assert history.status == "success" and history.file_name == path.name

    def test_content_privacy_and_limitations(self, world: World) -> None:
        world.service_record()
        request = ReportRequest(ReportType.VEHICLE_OVERVIEW, vehicle_id=world.vehicle.id)
        text = world.service.build(request).text_content()
        vin = world.vehicle.vin or ""
        assert vin and vin not in text
        assert "CAB-1234" not in text.upper()
        assert "Garage door code" not in text
        assert "Private maintenance note" not in text
        assert "not a certified vehicle safety system" in text.lower()
        assert "simulated" in text.lower()
        detailed = world.service.build(
            ReportRequest(
                ReportType.VEHICLE_OVERVIEW,
                vehicle_id=world.vehicle.id,
                include_identifiers=True,
                include_notes=True,
            )
        ).text_content()
        assert vin in detailed and "Garage door code" in detailed

    def test_repeated_findings_are_grouped_and_multi_page_tables_render(
        self, world: World, tmp_path: Path
    ) -> None:
        request = ReportRequest(
            ReportType.TRIP, vehicle_id=world.vehicle.id, session_id=world.trip_id
        )
        document = world.service.build(request)
        assert "episode 79" in document.text_content()
        path = render_pdf(document, tmp_path / "trip.pdf", compress=False)
        assert page_count(path) >= 3
        raw = path.read_bytes()
        assert raw.count(b"Page 1 of") == 1 and b"Trip report" in raw

    def test_trip_report_states_estimated_distance(self, world: World) -> None:
        text = world.service.build(
            ReportRequest(ReportType.TRIP, vehicle_id=world.vehicle.id, session_id=world.trip_id)
        ).text_content()
        assert "Estimated distance" in text
        assert "speed integration" in text

    def test_existing_file_is_not_replaced_without_permission(
        self, world: World, tmp_path: Path
    ) -> None:
        path = tmp_path / "report.pdf"
        path.write_bytes(b"keep me")
        request = ReportRequest(ReportType.MAINTENANCE, vehicle_id=world.vehicle.id)
        with pytest.raises(ExportError) as info:
            world.service.generate_pdf(request, path)
        assert info.value.user_message == "A file with that name already exists."
        assert path.read_bytes() == b"keep me"
        (failure,) = world.service.history()
        assert failure.status == "failed"
        world.service.generate_pdf(request, path, overwrite=True)
        assert path.read_bytes().startswith(b"%PDF-")

    def test_missing_folder_is_reported(self, world: World, tmp_path: Path) -> None:
        request = ReportRequest(ReportType.MAINTENANCE, vehicle_id=world.vehicle.id)
        with pytest.raises(ExportError) as info:
            world.service.generate_pdf(request, tmp_path / "missing" / "r.pdf")
        assert info.value.user_message == "The selected folder does not exist."

    @pytest.mark.parametrize("fmt", ["pdf", "csv"])
    def test_permission_errors_are_reported(
        self, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fmt: str
    ) -> None:
        def denied(*_args: object, **_kwargs: object) -> tuple[int, str]:
            raise PermissionError("Access is denied")

        monkeypatch.setattr("tempfile.mkstemp", denied)
        with pytest.raises(ExportError) as info:
            if fmt == "pdf":
                world.service.generate_pdf(
                    ReportRequest(ReportType.MAINTENANCE, vehicle_id=world.vehicle.id),
                    tmp_path / "r.pdf",
                )
            else:
                world.service.export_csv(
                    CsvDataset.TRIPS, tmp_path / "r.csv", vehicle_id=world.vehicle.id
                )
        assert "permission" in info.value.user_message
        assert world.service.history()[0].status == "failed"

    def test_text_outside_the_pdf_fonts_is_mapped(self) -> None:
        assert pdf_safe("≈ 5 km · 3 → 4 ✓") == "~ 5 km - 3 -> 4 yes"
        assert pdf_safe("温度") == "??"

    def test_render_rejects_nothing_silently(self, tmp_path: Path) -> None:
        document = ReportDocument(
            title="Empty",
            report_id="00000000-0000-0000-0000-000000000000",
            app_version="2.0.0",
            generated_at=datetime(2026, 11, 25, tzinfo=UTC),
            vehicle_label="None",
            period_label="None",
            data_source_label="No data",
            blocks=(),
        )
        assert render_pdf(document, tmp_path / "e.pdf").stat().st_size > 0


class TestGrouping:
    def test_consecutive_records_become_one_episode(self) -> None:
        base = {"source": "rule", "data_source": "simulation", "summary": "Coolant high"}
        findings = [
            {**base, "severity": "warning", "created_at": T0 + timedelta(seconds=s)}
            for s in (0, 10, 20, 30)
        ]
        findings.append({**base, "severity": "critical", "created_at": T0 + timedelta(seconds=40)})
        findings.append({**base, "severity": "warning", "created_at": T0 + timedelta(minutes=30)})
        episodes = group_findings(findings)
        assert [(e["severity"], e["count"]) for e in episodes] == [
            ("warning", 4),
            ("critical", 1),
            ("warning", 1),
        ]
        assert episodes[0]["last_seen"] == T0 + timedelta(seconds=30)


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


class TestCsv:
    def test_cells(self) -> None:
        assert format_cell(None) == ""
        assert format_cell(float("nan")) == ""
        assert format_cell(0.0) == 0.0  # a measured zero stays zero
        assert format_cell(True) == "true"
        assert format_cell(Decimal("12.50")) == "12.50"
        assert format_cell(datetime(2026, 1, 1, 8, tzinfo=UTC)) == "2026-01-01T08:00:00Z"
        for dangerous in ("=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tx", "\rx"):
            assert sanitise_text(dangerous).startswith("'")
        assert format_cell(-5) == -5  # numbers are not text and are not prefixed

    def test_escaping_round_trip_and_overwrite(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        rows = [["a, b", 'He said "hi"', "line\nbreak", None, "=cmd()"]]
        count = write_csv(path, [Column(c) for c in "vwxyz"], rows)
        assert count == 1
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert read_csv(path) == [
            list("vwxyz"),
            ["a, b", 'He said "hi"', "line\nbreak", "", "'=cmd()"],
        ]
        with pytest.raises(ExportError, match="already exists"):
            write_csv(path, [Column("a")], [])
        write_csv(path, [Column("a")], [[1]], overwrite=True)
        assert read_csv(path) == [["a"], ["1"]]
        assert not list(tmp_path.glob(".smartdrive-*"))

    def test_row_shape_errors_leave_no_partial_file(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.csv"
        with pytest.raises(ValueError):
            write_csv(path, [Column("a"), Column("b")], [[1]])
        assert not path.exists()
        assert not list(tmp_path.glob(".smartdrive-*"))

    @pytest.mark.parametrize("dataset", list(CsvDataset))
    def test_every_dataset_exports(self, world: World, tmp_path: Path, dataset: CsvDataset) -> None:
        world.scan()
        world.service_record()
        path = tmp_path / f"{dataset.value}.csv"
        result = world.service.export_csv(
            dataset, path, vehicle_id=world.vehicle.id, session_id=world.trip_id
        )
        rows = read_csv(path)
        assert result.rows == len(rows) - 1
        header = rows[0]
        assert len(set(header)) == len(header)
        assert all(len(r) == len(header) for r in rows)

    def test_telemetry_export_keeps_gaps_and_provenance(self, world: World, tmp_path: Path) -> None:
        path = tmp_path / "telemetry.csv"
        world.service.export_csv(
            CsvDataset.TELEMETRY, path, vehicle_id=world.vehicle.id, session_id=world.trip_id
        )
        header, *rows = read_csv(path)
        speed = header.index(next(h for h in header if h.startswith("speed")))
        assert rows[0][speed] == ""  # t=0 had no speed reading: empty, not 0
        assert rows[1][speed] == "60.0"
        assert any("simulation" in cell for cell in rows[0])
        assert rows[0][header.index("timestamp_utc")].endswith("Z")

    def test_maintenance_export_escapes_untrusted_text_and_omits_notes(
        self, world: World, tmp_path: Path
    ) -> None:
        world.service_record()
        path = tmp_path / "maintenance.csv"
        world.service.export_csv(CsvDataset.MAINTENANCE, path, vehicle_id=world.vehicle.id)
        header, row = read_csv(path)
        assert row[header.index("description")].startswith("'=HYPERLINK")
        assert row[header.index("provider")] == 'Garage, "Main" street'
        assert "Private maintenance note" not in path.read_text("utf-8-sig")

    def test_telemetry_needs_a_trip(self, world: World, tmp_path: Path) -> None:
        with pytest.raises(ExportError):
            world.service.export_csv(CsvDataset.TELEMETRY, tmp_path / "t.csv")
