"""Speech backend lifecycle, including Windows COM pairing (with a stand-in comtypes module)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from smartdrive.services import voice


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def getProperty(self, name: str) -> Any:  # noqa: N802 - pyttsx3 API
        return [types.SimpleNamespace(id="v1", name="Voice one")] if name == "voices" else None

    def setProperty(self, name: str, value: Any) -> None:  # noqa: N802 - pyttsx3 API
        self.calls.append((name, value))

    def say(self, text: str) -> None:
        self.calls.append(("say", text))

    def runAndWait(self) -> None:  # noqa: N802 - pyttsx3 API
        self.calls.append(("run", None))

    def stop(self) -> None:
        self.calls.append(("stop", None))


@pytest.fixture
def fake_com(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []
    module = types.ModuleType("comtypes")
    module.CoInitialize = lambda: events.append("init")  # type: ignore[attr-defined]
    module.CoUninitialize = lambda: events.append("uninit")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "comtypes", module)
    monkeypatch.setattr(voice, "_IS_WINDOWS", True)
    return events


def _fake_pyttsx3(monkeypatch: pytest.MonkeyPatch, init: Any) -> None:
    module = types.ModuleType("pyttsx3")
    module.init = init  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyttsx3", module)


def test_com_is_initialised_once_and_released_on_close(
    fake_com: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = FakeEngine()
    _fake_pyttsx3(monkeypatch, lambda: engine)
    backend = voice.Pyttsx3Backend()
    assert fake_com == ["init"]
    backend.speak("Coolant temperature high", voice_id="v1", rate=170, volume=0.8)
    assert ("say", "Coolant temperature high") in engine.calls
    assert backend.voices() == [voice.VoiceInfo("v1", "Voice one")]
    backend.close()
    backend.close()  # idempotent: never uninitialise twice
    assert fake_com == ["init", "uninit"]


def test_com_is_released_when_the_engine_fails_to_start(
    fake_com: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise RuntimeError("no SAPI voices")

    _fake_pyttsx3(monkeypatch, broken)
    backend = voice.create_backend()
    assert not backend.available
    assert "RuntimeError" in (backend.unavailable_reason or "")
    assert fake_com == ["init", "uninit"]


def test_failed_com_initialisation_is_not_balanced_by_uninitialise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    module = types.ModuleType("comtypes")

    def fail() -> None:
        raise OSError("COM unavailable")

    module.CoInitialize = fail  # type: ignore[attr-defined]
    module.CoUninitialize = lambda: events.append("uninit")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "comtypes", module)
    monkeypatch.setattr(voice, "_IS_WINDOWS", True)
    _fake_pyttsx3(monkeypatch, FakeEngine)
    backend = voice.Pyttsx3Backend()
    backend.close()
    assert events == []


def test_no_com_calls_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice, "_IS_WINDOWS", False)
    monkeypatch.delitem(sys.modules, "comtypes", raising=False)
    _fake_pyttsx3(monkeypatch, FakeEngine)
    backend = voice.Pyttsx3Backend()
    backend.close()
    assert "comtypes" not in sys.modules
