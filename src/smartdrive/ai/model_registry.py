"""Trusted model loading.

Only artifacts listed in the manifest that ships inside the installed package are loaded, and
only after their SHA-256 matches the manifest. Joblib files are pickles and can execute code, so
the application never loads model files chosen by a user or downloaded at runtime. Artifacts
must also match the installed scikit-learn ``major.minor`` and the current feature schema.
"""

from __future__ import annotations

import hashlib
import json
import logging
import warnings
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Any, Final

import joblib
import sklearn

from smartdrive.ai.anomaly_detector import ARTIFACT_TYPE as ANOMALY_TYPE
from smartdrive.ai.anomaly_detector import AnomalyDetector
from smartdrive.ai.classifier import ARTIFACT_TYPE as CLASSIFIER_TYPE
from smartdrive.ai.classifier import FaultClassifier
from smartdrive.ai.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION

logger = logging.getLogger(__name__)

MANIFEST_NAME: Final = "manifest.json"
CLASSIFIER_NAME: Final = "fault_classifier"
ANOMALY_NAME: Final = "anomaly_detector"


def packaged_artifact_dir() -> Path:
    return Path(str(files("smartdrive.ai").joinpath("artifacts")))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LoadStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    INTEGRITY_FAILED = "integrity_failed"
    INCOMPATIBLE = "incompatible"
    LOAD_FAILED = "load_failed"


@dataclass(frozen=True)
class LoadedModels:
    classifier: FaultClassifier | None
    anomaly: AnomalyDetector | None
    status: dict[str, LoadStatus]
    messages: dict[str, str]
    manifest: dict[str, dict[str, Any]]

    @property
    def any_available(self) -> bool:
        return self.classifier is not None or self.anomaly is not None


def _major_minor(version: str) -> tuple[str, ...]:
    return tuple(version.split(".")[:2])


class ModelRegistry:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or packaged_artifact_dir()

    def manifest(self) -> dict[str, dict[str, Any]]:
        path = self.directory / MANIFEST_NAME
        if not path.is_file():
            return {}
        data = json.loads(path.read_text("utf-8"))
        return {entry["name"]: entry for entry in data.get("models", [])}

    def _load_artifact(self, entry: dict[str, Any], expected_type: str) -> dict[str, Any]:
        path = (self.directory / Path(entry["file"]).name).resolve()
        if not path.is_file():
            raise FileNotFoundError(path.name)
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise _IntegrityError(f"{path.name}: SHA-256 {actual[:12]}… does not match manifest.")
        if _major_minor(entry.get("sklearn_version", "")) != _major_minor(sklearn.__version__):
            raise _CompatibilityError(
                f"Trained with scikit-learn {entry.get('sklearn_version')}, installed "
                f"{sklearn.__version__}."
            )
        if entry.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            raise _CompatibilityError(
                f"Feature schema {entry.get('feature_schema_version')} != {FEATURE_SCHEMA_VERSION}."
            )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            artifact = joblib.load(path)
        if not isinstance(artifact, dict) or artifact.get("artifact_type") != expected_type:
            raise _CompatibilityError("Artifact type is not what the manifest declares.")
        if tuple(artifact.get("feature_names", ())) != FEATURE_NAMES:
            raise _CompatibilityError("Artifact feature names differ from the current schema.")
        return artifact

    def load(self) -> LoadedModels:
        manifest = self.manifest()
        status: dict[str, LoadStatus] = {}
        messages: dict[str, str] = {}
        loaded: dict[str, Any] = {}
        for name, artifact_type, factory in (
            (CLASSIFIER_NAME, CLASSIFIER_TYPE, FaultClassifier.from_artifact),
            (ANOMALY_NAME, ANOMALY_TYPE, AnomalyDetector.from_artifact),
        ):
            entry = manifest.get(name)
            if entry is None:
                status[name], messages[name] = LoadStatus.MISSING, "Not listed in the manifest."
                continue
            try:
                artifact = self._load_artifact(entry, artifact_type)
                loaded[name] = factory(artifact, entry["version"])
                status[name], messages[name] = LoadStatus.AVAILABLE, f"Version {entry['version']}"
            except FileNotFoundError as exc:
                status[name], messages[name] = LoadStatus.MISSING, f"File not found: {exc}"
            except _IntegrityError as exc:
                status[name], messages[name] = LoadStatus.INTEGRITY_FAILED, str(exc)
            except _CompatibilityError as exc:
                status[name], messages[name] = LoadStatus.INCOMPATIBLE, str(exc)
            except Exception as exc:
                status[name], messages[name] = (
                    LoadStatus.LOAD_FAILED,
                    f"{type(exc).__name__}: {exc}",
                )
            if status[name] is not LoadStatus.AVAILABLE:
                logger.warning(
                    "Model not loaded",
                    extra={"model": name, "status": status[name], "detail": messages[name]},
                )
        return LoadedModels(
            loaded.get(CLASSIFIER_NAME), loaded.get(ANOMALY_NAME), status, messages, manifest
        )


class _IntegrityError(Exception):
    pass


class _CompatibilityError(Exception):
    pass
