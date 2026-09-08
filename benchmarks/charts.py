"""Latency and throughput charts for the slim bench suite."""

from __future__ import annotations

from pathlib import Path

from benchmarks.report import BenchReport

CHARTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "charts"

STALE_CHARTS = (
    "warm_latency.png",
    "writer_concurrency.png",
    "multi_db_scaleout.png",
    "cold_vs_warm.png",
)


class ChartTheme:
    """GitHub-dark cards so the PNGs sit in a README without extra chrome."""

    bg = "#0d1117"
    panel = "#161b22"
    text = "#e6edf3"
    muted = "#8b949e"
    grid = "#30363d"
    read = "#58a6ff"
    write = "#d29922"
    push = "#f0883e"
    pull = "#a371f7"

    def figure(self):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8.4, 4.1), facecolor=self.bg)
        ax.set_facecolor(self.panel)
        fig.subplots_adjust(left=0.14, right=0.96, top=0.82, bottom=0.16)
        return fig, ax

    def finish(self, ax, title: str, ylabel: str, ymax: float) -> None:
        ax.set_title(title, color=self.text, fontsize=15, fontweight="bold", pad=16)
        ax.set_ylabel(ylabel, color=self.muted, fontsize=10)
        ax.tick_params(colors=self.muted, length=0, labelsize=11)
        ax.set_ylim(0, ymax)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.yaxis.grid(True, color=self.grid, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.xaxis.grid(False)

    def label_bars(self, ax, bars, texts: list[str]) -> None:
        for bar, text in zip(bars, texts, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                text,
                ha="center",
                va="bottom",
                color=self.text,
                fontsize=11,
                fontweight="bold",
            )


def _fmt_ms(value: float) -> str:
    if value < 1:
        return f"{value:.2f} ms"
    return f"{value:.0f} ms"


def _fmt_ops(value: float) -> str:
    return f"{value / 1000:.1f}k/s" if value < 100_000 else f"{value / 1000:.0f}k/s"


def render_charts(report: BenchReport, out_dir: Path | None = None) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dest = out_dir if out_dir is not None else CHARTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    theme = ChartTheme()

    def save(fig, filename: str) -> None:
        path = dest / filename
        fig.savefig(
            path,
            dpi=180,
            facecolor=fig.get_facecolor(),
            edgecolor="none",
            bbox_inches="tight",
            pad_inches=0.32,
        )
        plt.close(fig)
        written.append(path)

    lat = report["local_latency"]
    thr = report["local_throughput"]
    sync = report["sync_latency"]

    fig, ax = theme.figure()
    labels = ["Read", "Write (commit)"]
    values = [lat["read_ms"]["p50"], lat["write_ms"]["p50"]]
    bars = ax.bar(
        labels, values, width=0.52, color=[theme.read, theme.write], linewidth=0
    )
    theme.finish(ax, "Local SQL latency", "p50 (ms)", max(values) * 1.28)
    theme.label_bars(ax, bars, [_fmt_ms(v) for v in values])
    save(fig, "latency.png")

    fig, ax = theme.figure()
    labels = ["Push", "Pull"]
    values = [sync["push_ms"]["p50"], sync["pull_ms"]["p50"]]
    bars = ax.bar(
        labels, values, width=0.52, color=[theme.push, theme.pull], linewidth=0
    )
    theme.finish(ax, "Warm sync to your Server", "p50 (ms)", max(values) * 1.28)
    theme.label_bars(ax, bars, [_fmt_ms(v) for v in values])
    save(fig, "sync_latency.png")

    fig, ax = theme.figure()
    labels = ["Read", "Write (commit)"]
    values = [thr["read_ops_per_s"], thr["write_ops_per_s"]]
    bars = ax.bar(
        labels, values, width=0.52, color=[theme.read, theme.write], linewidth=0
    )
    theme.finish(ax, "Local SQL throughput", "ops / s", max(values) * 1.28)
    theme.label_bars(ax, bars, [_fmt_ops(v) for v in values])
    save(fig, "throughput.png")

    for name in STALE_CHARTS:
        stale = dest / name
        if stale.exists():
            stale.unlink()

    return written
