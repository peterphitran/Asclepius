import os
import tomllib
from pathlib import Path

from pydantic import ValidationError

from asclepius.domain import AppError, EvaluatorConfig, ProfileConfig, SubmissionPlan


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
        return override.resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return (base / "Asclepius").resolve()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / "asclepius").resolve()
