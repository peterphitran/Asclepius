import os
import ssl
import tomllib
from pathlib import Path

from pydantic import Field, ValidationError

from asclepius.domain import (
    AppError,
    Contract,
    EvaluatorConfig,
    Limits,
    ProfileConfig,
    SubmissionPlan,
)
from asclepius.paths import local_directory


def _read(path: Path) -> dict:
    try:
        with path.open("rb") as source:
            content = source.read(1048577)
    except OSError:
        raise AppError("config_read", "Cannot read configuration file.", 2) from None
    if len(content) > 1048576:
        raise AppError("config_size", "Configuration exceeds the 1 MiB limit.", 2)
    try:
        return tomllib.loads(content.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise AppError("config_syntax", "Invalid TOML configuration.", 2) from None


def load_target(path: Path) -> ProfileConfig:
    try:
        config = ProfileConfig.model_validate(_read(path))
    except ValidationError:
        raise AppError("config_validation", "Invalid target fields or values.", 2) from None
    return config


def load_evaluator(path: Path) -> EvaluatorConfig:
    try:
        config = EvaluatorConfig.model_validate(_read(path))
    except ValidationError:
        raise AppError("config_validation", "Invalid evaluator fields or values.", 2) from None
    return config


def load_plan(path: Path) -> SubmissionPlan:
    try:
        with path.open("rb") as source:
            content = source.read(1048577)
    except OSError:
        raise AppError("config_read", "Cannot read evaluation plan.", 2) from None
    if len(content) > 1048576:
        raise AppError("config_size", "Evaluation plan exceeds the 1 MiB limit.", 2)
    try:
        return SubmissionPlan.model_validate_json(content)
    except ValidationError:
        raise AppError("invalid_plan", "Invalid evaluation plan fields or values.", 2) from None


def data_directory(override: Path | None = None) -> Path:
    if override is not None:
        return local_directory(override)
    if os.name == "nt":
        base = _absolute_env("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return local_directory(base / "Asclepius")
    base = _absolute_env("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return local_directory(base / "asclepius")


def _absolute_env(name: str, default: Path) -> Path:
    value = os.environ.get(name, "")
    return Path(value) if value and Path(value).is_absolute() else default


class DaemonConfig(Contract):
    limits: Limits = Field(default_factory=Limits)
    ca_bundle: str | None = None


def load_daemon(path: Path | None = None) -> DaemonConfig:
    try:
        config = DaemonConfig.model_validate(_read(path) if path else {})
        if config.ca_bundle is not None:
            bundle = Path(config.ca_bundle)
            if not bundle.is_absolute():
                bundle = path.parent / bundle
            bundle = bundle.resolve(strict=True)
            context = ssl.create_default_context()
            context.load_verify_locations(cafile=str(bundle))
            config = config.model_copy(update={"ca_bundle": str(bundle)})
        return config
    except (ValidationError, OSError, ValueError, ssl.SSLError):
        raise AppError("daemon_config", "Invalid daemon policy or CA bundle.", 2) from None
