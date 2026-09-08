"""Benchmark remotes: create options and resolution."""

from __future__ import annotations

from sqlite_modal import Sqlite
from sqlite_modal.exceptions import MissingError
from sqlite_modal.remote import CreateOptions

REGION = "uk"
ROUTING_REGION = "eu-west"
COLD_SCALEDOWN_S = 15
COLD_WAIT_S = float(COLD_SCALEDOWN_S + 20)

WARM_OPTIONS: CreateOptions = {
    "min_containers": 1,
    "compute_region": REGION,
    "routing_region": ROUTING_REGION,
}
COLD_OPTIONS: CreateOptions = {
    "min_containers": 0,
    "scaledown_window": COLD_SCALEDOWN_S,
    "compute_region": REGION,
    "routing_region": ROUTING_REGION,
}

WARM_NAME = "bench"
COLD_NAME = "bench_cold"


def resolve(name: str, *, create: bool, options: CreateOptions) -> Sqlite:
    """Lookup an existing remote, or deploy when ``create`` is set."""
    if create:
        return Sqlite.from_name(
            name,
            create_if_missing=True,
            create_options=options,
        )
    try:
        return Sqlite.from_name(name)
    except MissingError:
        raise MissingError(
            f"Sqlite {name!r} does not exist; "
            "re-run with --create-remotes once to deploy bench remotes"
        ) from None
