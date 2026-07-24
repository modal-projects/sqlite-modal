"""Product-shaped charts for the Sync adoption suite."""

from __future__ import annotations

from pathlib import Path

from benchmarks.report import BenchReport

CHARTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "charts"

_BLUE = "#1f6feb"
_ORANGE = "#e8590c"
_GREEN = "#2f9e44"
_GRAY = "#868e96"
_PURPLE = "#9c36b5"


def render_charts(report: BenchReport, out_dir: Path | None = None) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dest = out_dir if out_dir is not None else CHARTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(fig: plt.Figure, filename: str) -> None:
        path = dest / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        written.append(path)

    def label_bars(ax: plt.Axes, bars: object, values: list[float], fmt: str) -> None:
        for bar, val in zip(bars, values, strict=True):  # type: ignore[arg-type]
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                val,
                fmt.format(val),
                ha="center",
                va="bottom",
                fontsize=9,
            )

    warm = report["warm_latency"]
    conc = report["writer_concurrency"]
    multi = report["multi_db_parallel"]
    cold = report["cold_start"]

    # Local SQL is sub-ms; sync is ~100ms — split axes so both remain readable.
    fig, (ax_local, ax_sync) = plt.subplots(
        1, 2, figsize=(9.5, 4.0), constrained_layout=True
    )
    local_labels = ["Read", "Write\n(commit)"]
    local_vals = [warm["read_ms"]["p50"], warm["write_ms"]["p50"]]
    bars_local = ax_local.bar(local_labels, local_vals, color=[_GREEN, _BLUE])
    ax_local.set_ylabel("p50 (ms)")
    ax_local.set_title("Local SQL (embedded file)")
    label_bars(ax_local, bars_local, local_vals, "{:.2f}")

    sync_labels = ["Push", "Pull"]
    sync_vals = [warm["push_ms"]["p50"], warm["pull_ms"]["p50"]]
    bars_sync = ax_sync.bar(sync_labels, sync_vals, color=[_ORANGE, _PURPLE])
    ax_sync.set_ylabel("p50 (ms)")
    ax_sync.set_title("Warm sync to Modal Server")
    label_bars(ax_sync, bars_sync, sync_vals, "{:.0f}")
    save(fig, "warm_latency.png")

    fig, (ax_ops, ax_lat) = plt.subplots(
        1, 2, figsize=(9.5, 4.0), constrained_layout=True
    )
    clients = [p["clients"] for p in conc["points"]]
    ops = [p["ops_per_s"] for p in conc["points"]]
    lats = [p["latency_ms"]["p50"] for p in conc["points"]]
    ax_ops.plot(clients, ops, marker="o", color=_BLUE, linewidth=2)
    ax_ops.set_xlabel("Concurrent push clients")
    ax_ops.set_ylabel("ops / s")
    ax_ops.set_title("Throughput vs concurrency (one remote)")
    ax_ops.set_xticks(clients)
    ax_lat.plot(clients, lats, marker="o", color=_ORANGE, linewidth=2)
    ax_lat.set_xlabel("Concurrent push clients")
    ax_lat.set_ylabel("Insert+push p50 (ms)")
    ax_lat.set_title("Latency vs concurrency (one remote)")
    ax_lat.set_xticks(clients)
    save(fig, "writer_concurrency.png")

    fig, ax = plt.subplots(figsize=(7.5, 4.2), constrained_layout=True)
    labels = ["1 DB", "2 DBs\n(combined)"]
    values = [
        multi["single_db_ops_per_s"],
        multi["dual_combined_ops_per_s"],
    ]
    bars = ax.bar(labels, values, color=[_BLUE, _GREEN])
    ax.set_ylabel("Push-write ops / s")
    ax.set_title("Write throughput: one named DB vs two in parallel")
    label_bars(ax, bars, values, "{:.0f}")
    save(fig, "multi_db_scaleout.png")

    if cold is not None:
        fig, ax = plt.subplots(figsize=(7.5, 4.2), constrained_layout=True)
        labels = ["Cold first connect+push", "Warm push p50"]
        values = [cold["cold_first_ms"], cold["warm_p50_ms"]]
        bars = ax.bar(labels, values, color=[_ORANGE, _BLUE])
        ax.set_ylabel("Latency (ms)")
        ax.set_title("After scale-to-zero vs warm push")
        if all(v > 0 for v in values):
            ax.set_yscale("log")
        for bar, val in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                max(val, 1e-3),
                f"{val:.0f} ms",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        ax.annotate(
            cold["note"],
            xy=(0.5, 0.02),
            xycoords="axes fraction",
            ha="center",
            va="bottom",
            fontsize=8,
            color=_GRAY,
        )
        save(fig, "cold_vs_warm.png")

    return written
