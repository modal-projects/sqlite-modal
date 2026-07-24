"""Latency and throughput charts for the slim bench suite."""

from __future__ import annotations

from pathlib import Path

from benchmarks.report import BenchReport

CHARTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "charts"

_BLUE = "#1f6feb"
_GREEN = "#2f9e44"
_ORANGE = "#e8590c"
_PURPLE = "#9c36b5"

STALE_CHARTS = (
    "warm_latency.png",
    "writer_concurrency.png",
    "multi_db_scaleout.png",
    "cold_vs_warm.png",
)


def render_charts(report: BenchReport, out_dir: Path | None = None) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.container import BarContainer

    dest = out_dir if out_dir is not None else CHARTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(fig: plt.Figure, filename: str) -> None:
        path = dest / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        written.append(path)

    def label_bars(
        ax: plt.Axes, bars: BarContainer, values: list[float], fmt: str
    ) -> None:
        for bar, val in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                val,
                fmt.format(val),
                ha="center",
                va="bottom",
                fontsize=9,
            )

    lat = report["local_latency"]
    thr = report["local_throughput"]
    sync = report["sync_latency"]

    fig, ax = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    labels = ["Read", "Write\n(commit)"]
    values = [lat["read_ms"]["p50"], lat["write_ms"]["p50"]]
    bars = ax.bar(labels, values, color=[_GREEN, _BLUE])
    ax.set_ylabel("p50 (ms)")
    ax.set_title("Local SQL latency")
    label_bars(ax, bars, values, "{:.2f}")
    save(fig, "latency.png")

    fig, ax = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    labels = ["Push", "Pull"]
    values = [sync["push_ms"]["p50"], sync["pull_ms"]["p50"]]
    bars = ax.bar(labels, values, color=[_ORANGE, _PURPLE])
    ax.set_ylabel("p50 (ms)")
    ax.set_title("Warm sync latency (Modal Server)")
    label_bars(ax, bars, values, "{:.0f}")
    save(fig, "sync_latency.png")

    fig, ax = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    labels = ["Read", "Write\n(commit)"]
    values = [thr["read_ops_per_s"], thr["write_ops_per_s"]]
    bars = ax.bar(labels, values, color=[_GREEN, _BLUE])
    ax.set_ylabel("ops / s")
    ax.set_title("Local SQL throughput")
    label_bars(ax, bars, values, "{:.0f}")
    save(fig, "throughput.png")

    for name in STALE_CHARTS:
        stale = dest / name
        if stale.exists():
            stale.unlink()

    return written
