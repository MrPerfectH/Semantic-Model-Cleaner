"""Release channel and experiment gating for beta features."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Experiment:
    key: str
    label: str
    description: str


KNOWN_EXPERIMENTS = {
    "compare-models": Experiment(
        key="compare-models",
        label="Model Compare",
        description="Early-access model comparison flow and prerelease UI surfaces.",
    ),
}


def release_channel(raw: str | None = None) -> str:
    value = (raw if raw is not None else os.getenv("SMC_RELEASE_CHANNEL", "stable")).strip().lower()
    if value in {"beta", "preview", "prerelease"}:
        return "beta"
    return "stable"


def active_experiment_keys(
    raw: str | None = None,
    *,
    extra: list[str] | None = None,
) -> list[str]:
    values: list[str] = []
    env_value = raw if raw is not None else os.getenv("SMC_EXPERIMENTS", "")
    if env_value:
        values.extend(part.strip().lower() for part in env_value.split(","))
    if extra:
        values.extend(part.strip().lower() for part in extra)

    unique = []
    seen = set()
    for value in values:
        if not value or value not in KNOWN_EXPERIMENTS or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def runtime_config(
    *,
    raw_channel: str | None = None,
    raw_experiments: str | None = None,
    extra_experiments: list[str] | None = None,
) -> dict:
    channel = release_channel(raw_channel)
    active_keys = active_experiment_keys(raw_experiments, extra=extra_experiments)
    active = [KNOWN_EXPERIMENTS[key] for key in active_keys]
    return {
        "releaseChannel": channel,
        "betaEnabled": channel == "beta" or bool(active),
        "activeExperiments": [
            {
                "key": item.key,
                "label": item.label,
                "description": item.description,
            }
            for item in active
        ],
    }
