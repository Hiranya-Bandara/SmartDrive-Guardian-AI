from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from smartdrive.config.constants import HOME_ENV_VAR, ThemePreference
from smartdrive.config.paths import AppPaths
from smartdrive.config.settings import AppSettings, SettingsStore


class TestAppPaths:
    def test_environment_variable_relocates_all_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "portable"))
        paths = AppPaths.resolve()
        root = (tmp_path / "portable").resolve()
        for directory in (paths.data_dir, paths.config_dir, paths.log_dir, paths.backup_dir):
            assert directory.is_relative_to(root)

    def test_explicit_override_wins_over_environment(self, tmp_path: Path) -> None:
        paths = AppPaths.resolve(tmp_path / "explicit")
        assert paths.database_file == (tmp_path / "explicit" / "data" / "smartdrive.db").resolve()

    def test_default_location_is_outside_the_source_tree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(HOME_ENV_VAR, raising=False)
        repo_root = Path(__file__).resolve().parents[2]
        paths = AppPaths.resolve()
        assert not paths.data_dir.resolve().is_relative_to(repo_root)

    def test_ensure_creates_writable_directories(self, tmp_path: Path) -> None:
        paths = AppPaths.under(tmp_path).ensure()
        assert paths.data_dir.is_dir()
        assert paths.log_dir.is_dir()
        assert paths.backup_dir.is_dir()


class TestSettings:
    def test_defaults_are_safe(self) -> None:
        settings = AppSettings()
        assert settings.appearance.theme is ThemePreference.DARK
        assert settings.privacy.redact_identifiers_in_logs is True
        assert settings.alerts.voice_notifications is False
        assert settings.obd.port is None

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        assert SettingsStore(tmp_path / "settings.json").load() == AppSettings()

    def test_round_trip_persists_changes(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "settings.json")
        settings = AppSettings()
        settings.appearance.theme = ThemePreference.LIGHT
        settings.monitoring.refresh_interval_ms = 500
        store.save(settings)
        reloaded = store.load()
        assert reloaded.appearance.theme is ThemePreference.LIGHT
        assert reloaded.monitoring.refresh_interval_ms == 500

    def test_save_leaves_no_temporary_files(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "settings.json")
        store.save(AppSettings())
        assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]

    @pytest.mark.parametrize("interval", [0, 50, 60_000])
    def test_out_of_range_values_are_rejected(self, interval: int) -> None:
        with pytest.raises(ValidationError):
            AppSettings().monitoring.refresh_interval_ms = interval

    def test_corrupt_file_is_quarantined_and_defaults_used(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{not json", encoding="utf-8")
        settings = SettingsStore(path).load()
        assert settings == AppSettings()
        assert not path.exists()
        assert len(list(tmp_path.glob("settings.corrupt-*.json"))) == 1

    def test_invalid_values_in_file_are_quarantined(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"monitoring": {"refresh_interval_ms": -5}}), encoding="utf-8")
        assert SettingsStore(path).load() == AppSettings()

    def test_unknown_keys_from_newer_versions_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"appearance": {"theme": "light", "future_option": 1}, "future": {}}),
            encoding="utf-8",
        )
        assert SettingsStore(path).load().appearance.theme is ThemePreference.LIGHT

    def test_reset_restores_defaults_on_disk(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "settings.json")
        changed = AppSettings()
        changed.units.system = "imperial"  # type: ignore[assignment]
        store.save(changed)
        assert store.reset() == AppSettings()
        assert store.load() == AppSettings()
