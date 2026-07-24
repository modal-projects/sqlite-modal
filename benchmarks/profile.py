"""Break down latencies against a Server-backed Sqlite.

```bash
uv run python benchmarks/profile.py
```
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from sqlite_modal import Sqlite

ROUNDS = 12
HERE = Path(__file__).resolve().parent / "results" / "workdir"
HERE.mkdir(parents=True, exist_ok=True)
LOCAL = HERE / "profile.db"
OUT = Path(__file__).resolve().parent / "results" / "profile.json"


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return s[i]


def summarize(xs: list[float]) -> dict[str, float]:
    return {
        "n": float(len(xs)),
        "p50_ms": round(statistics.median(xs), 2),
        "p95_ms": round(pct(xs, 95), 2),
        "min_ms": round(min(xs), 2),
        "max_ms": round(max(xs), 2),
        "mean_ms": round(statistics.fmean(xs), 2),
    }


def main() -> None:
    for p in HERE.glob("profile*.db*"):
        p.unlink()

    results: dict[str, object] = {"rounds": ROUNDS}

    t0 = time.perf_counter()
    db = Sqlite.from_name(
        "profile_demo",
        create_if_missing=True,
        create_options={
            "max_containers": 1,
            "min_containers": 1,
            "startup_timeout": 120,
        },
    )
    results["from_name_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    t0 = time.perf_counter()
    url = db.remote_url
    results["cold_remote_url_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    results["remote_url"] = url
    if "?" in url:
        raise RuntimeError(f"remote_url must be bare (no query string): {url}")

    warm: list[float] = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        _ = db.remote_url
        warm.append((time.perf_counter() - t0) * 1000)
    results["warm_remote_url"] = summarize(warm)

    # Servers return 503 until the container is listening.
    deadline = time.monotonic() + 180
    last_exc: BaseException | None = None
    conn = None
    t0 = time.perf_counter()
    while time.monotonic() < deadline:
        try:
            conn = db.connect(LOCAL)
            break
        except Exception as exc:
            last_exc = exc
            time.sleep(1)
    if conn is None:
        raise RuntimeError(f"connect failed after wait: {last_exc}")
    results["first_connect_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)"
        )
        conn.commit()
        t0 = time.perf_counter()
        conn.push()
        results["first_push_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    connect_only: list[float] = []
    local_only: list[float] = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        conn = db.connect(LOCAL)
        connect_only.append((time.perf_counter() - t0) * 1000)
        with conn:
            t0 = time.perf_counter()
            conn.execute("INSERT INTO t (v) VALUES (?)", ("x",))
            conn.commit()
            local_only.append((time.perf_counter() - t0) * 1000)
    results["connect"] = summarize(connect_only)
    results["local_insert_commit"] = summarize(local_only)

    push_ms: list[float] = []
    pull_ms: list[float] = []
    conn = db.connect(LOCAL)
    with conn:
        for i in range(ROUNDS):
            conn.execute("INSERT INTO t (v) VALUES (?)", (f"p{i}",))
            conn.commit()
            t0 = time.perf_counter()
            conn.push()
            push_ms.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            conn.pull()
            pull_ms.append((time.perf_counter() - t0) * 1000)
    results["push"] = summarize(push_ms)
    results["pull"] = summarize(pull_ms)

    combo: list[float] = []
    for i in range(ROUNDS):
        t0 = time.perf_counter()
        conn = db.connect(LOCAL)
        with conn:
            conn.execute("INSERT INTO t (v) VALUES (?)", (f"c{i}",))
            conn.commit()
            conn.push()
            conn.pull()
        combo.append((time.perf_counter() - t0) * 1000)
    results["reconnect_insert_push_pull"] = summarize(combo)

    local2 = HERE / "profile2.db"
    for p in HERE.glob("profile2.db*"):
        p.unlink()
    t0 = time.perf_counter()
    conn2 = db.connect(local2)
    results["second_connect_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    with conn2:
        t0 = time.perf_counter()
        changed = conn2.pull()
        results["second_bootstrap_pull_ms"] = round(
            (time.perf_counter() - t0) * 1000, 2
        )
        results["second_pull_changed"] = changed

    OUT.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
