"""Lightweight latency probes against a deployed remote."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from sqlite_modal import Sqlite

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
LOCAL_DB = HERE / ".bench.db"


def main(rounds: int = 20) -> None:
    db = Sqlite.from_name(
        "bench_demo",
        create_if_missing=True,
        create_options={"max_containers": 1},
    )
    if LOCAL_DB.exists():
        LOCAL_DB.unlink()

    conn = db.connect(LOCAL_DB)
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)"
        )
        conn.commit()
        conn.push()

    local_ms: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        conn = db.connect(LOCAL_DB)
        with conn:
            conn.execute("INSERT INTO t (v) VALUES (?)", ("x",))
            conn.commit()
        local_ms.append((time.perf_counter() - t0) * 1000)

    sync_ms: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        conn = db.connect(LOCAL_DB)
        with conn:
            conn.execute("INSERT INTO t (v) VALUES (?)", ("y",))
            conn.commit()
            conn.push()
            conn.pull()
        sync_ms.append((time.perf_counter() - t0) * 1000)

    report = {
        "rounds": rounds,
        "local_insert_p50_ms": statistics.median(local_ms),
        "push_pull_p50_ms": statistics.median(sync_ms),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
