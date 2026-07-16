"""Render benchmark charts from a BenchReport."""

from __future__ import annotations

from pathlib import Path

from benchmarks.report import BenchReport

CHARTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "charts"


def render_charts(
    report: BenchReport, out_dir: Path | None = None
) -> list[Path]:
    """Write PNG bar charts; returns paths written."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dest = out_dir if out_dir is not None else CHARTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save_bar(
        filename: str,
        title: str,
        ylabel: str,
        labels: list[str],
        values: list[float],
        colors: list[str],
    ) -> None:
        fig, ax = plt.subplots(figsize=(7, 4))
        bars = ax.bar(labels, values, color=colors[: len(labels)])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        for bar, val in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{val:.0f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        fig.tight_layout()
        path = dest / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        written.append(path)

    rtt = report["rtt_floor"]
    batch = report["single_vs_batch"]
    flush = report["flush_cost"]
    thr = report["throughput"]

    save_bar(
        "latency.png",
        "HTTP RTT floor (p50)",
        "ms",
        ["health", "SELECT 1", "INSERT"],
        [
            rtt["health_ms"]["p50"],
            rtt["select1_ms"]["p50"],
            rtt["insert_ms"]["p50"],
        ],
        ["#1f6feb", "#1a7f37", "#8250df"],
    )
    save_bar(
        "throughput.png",
        "Sequential HTTP throughput",
        "ops / s",
        ["writes", "reads"],
        [thr["writes"]["ops_per_s"], thr["reads"]["ops_per_s"]],
        ["#1f6feb", "#1a7f37"],
    )
    save_bar(
        "batching.png",
        "Batching amortizes HTTP round-trips",
        "throughput",
        ["single execute\n(ops/s)", "batch params_seq\n(rows/s)"],
        [
            batch["single_execute"]["ops_per_s"],
            batch["batch_params_seq"]["rows_per_s"],
        ],
        ["#1f6feb", "#1a7f37"],
    )
    save_bar(
        "flush.png",
        "flush() is a sync volume.commit barrier",
        "ms (p50)",
        ["INSERT", "INSERT + flush"],
        [
            flush["insert_ms"]["p50"],
            flush["insert_and_flush_ms"]["p50"],
        ],
        ["#1f6feb", "#cf222e"],
    )
    return written
