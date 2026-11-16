import csv
from datetime import datetime
from html import escape

from .metrics import METRICS

TITLE = "Benchmark results"
SUMMARY_COLUMNS = ("n", "median", "ci_low", "ci_high", "p25", "p75", "min", "max", "mean", "sd")
STYLE = """
:root { --bg: #ffffff; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7; --head: #f5f5f7; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161618; --fg: #ececf0; --muted: #9a9aa2; --line: #3a3a40; --head: #222226; }
}
body { background: var(--bg); color: var(--fg); font: 14px/1.45 system-ui, sans-serif; margin: 24px; }
h1 { font-size: 22px; } h2 { font-size: 18px; margin-top: 36px; } h3 { font-size: 15px; margin-top: 24px; }
p, li { max-width: 72em; } .muted { color: var(--muted); }
.scroll { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; margin: 8px 0; font-variant-numeric: tabular-nums; }
th, td { border: 1px solid var(--line); padding: 3px 7px; text-align: right; white-space: nowrap; }
th { background: var(--head); font-weight: 600; }
th.row, td.row { text-align: left; }
td.na { color: var(--muted); font-style: italic; } td.best { font-weight: 700; }
details { margin: 8px 0; } summary { cursor: pointer; }
"""


class Report:
    def __init__(self, matrix, percentiles, confidence):
        self.matrix = matrix
        self.percentiles = percentiles
        self.confidence = confidence
        self.metrics = [metric for definition in METRICS for metric in definition.metrics(percentiles)]

    def write(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self._write_runs(directory / "runs.csv")
        self._write_cells(directory / "cells.csv")
        (directory / "report.html").write_text(self.render())

    def render(self):
        sections = {}
        for metric in self.metrics:
            sections.setdefault(metric.section, []).append(metric)

        parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
                 f"<meta name=viewport content='width=device-width, initial-scale=1'>"
                 f"<title>{TITLE}</title><style>{STYLE}</style></head><body><h1>{TITLE}</h1>",
                 "<p>" + "<br>".join(escape(line) for line in self._info()) + "</p>",
                 "<h2>Runs</h2>", self._runs_table(), self._failed_runs(),
                 "<h2>Medians per scenario and workload</h2>",
                 f"<p class=muted>One row per metric and one column per configuration: the median over the "
                 f"usable runs of the cell; the best configuration is bold. Hover for the number of runs, the "
                 f"{self.confidence:.0%} confidence interval of the median (at least 6 runs) and the extremes.</p>"]
        for (scenario, workload), cells in self.matrix.groups().items():
            parts.append(f"<h3>{escape(scenario)} / {escape(workload)}</h3>")
            parts.append(self._median_sections(cells, sections))

        parts.append("<h2>Metrics</h2><ul>")
        for metric in self.metrics:
            notes = [f"{metric.better} is better" if metric.better else "no direction"]
            if metric.unit.name:
                notes.append(metric.unit.name)
            parts.append(f"<li><b>{escape(metric.name)}</b> ({escape(', '.join(notes))}): "
                         f"{escape(metric.description)}</li>")
        parts.append("</ul></body></html>")
        return "\n".join(parts)

    def _write_runs(self, path):
        with open(path, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["scenario", "workload", "config", "repetition", "run", "error",
                             *[metric.name for metric in self.metrics]])
            for run in self.matrix.runs:
                values = [self._csv(metric.value(run.summary)) for metric in self.metrics]
                writer.writerow([run.scenario, run.workload, run.config, run.repetition, run.name,
                                 run.error or "", *values])

    def _write_cells(self, path):
        with open(path, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["scenario", "workload", "config", "runs", "usable_runs", "metric", *SUMMARY_COLUMNS])
            for cell in self.matrix.cells:
                usable = len(cell.usable())
                for metric in self.metrics:
                    summary = cell.summary(metric, self.confidence)
                    writer.writerow([cell.scenario, cell.workload, cell.config, len(cell.runs), usable, metric.name,
                                     *[self._csv(summary.get(column)) for column in SUMMARY_COLUMNS]])

    def _info(self):
        distributions = "every statistic" if self.percentiles else "median only (every statistic with --percentiles)"
        return [f"Runs: {len(self.matrix.runs)} from {self.matrix.root}",
                f"{len(self.matrix.groups())} scenario/workload groups, {len(self.matrix.configurations())} "
                f"configurations, {len(self.matrix.cells)} cells",
                f"Distributions of a run: {distributions}",
                f"Generated {datetime.now().isoformat(timespec='seconds')}"]

    def _runs_table(self):
        parts = ["<table><tr><th class=row>configuration</th><th>runs</th><th>usable</th>"
                 "<th>without h2load.json</th></tr>"]
        for config, total, usable in self.matrix.configurations():
            parts.append(f"<tr><td class=row>{escape(config)}</td><td>{total}</td><td>{usable}</td>"
                         f"<td>{total - usable}</td></tr>")
        parts.append("</table>")
        return "".join(parts)

    def _failed_runs(self):
        failed = self.matrix.failed()
        if not failed:
            return "<p class=muted>Every run has a usable h2load.json.</p>"

        parts = [f"<details><summary>Runs without a usable h2load.json ({len(failed)})</summary>"
                 "<div class=scroll><table><tr><th class=row>run</th><th class=row>reason</th></tr>"]
        for run in failed:
            parts.append(f"<tr><td class=row>{escape(str(run.name))}</td><td class=row>{escape(run.error)}</td></tr>")
        parts.append("</table></div></details>")
        return "".join(parts)

    def _median_sections(self, cells, sections):
        parts = []
        for name, metrics in sections.items():
            if any(cell.values(metric) for metric in metrics for cell in cells):
                parts.append(f"<details><summary>{escape(name)} ({len(metrics)} metrics)"
                             f"</summary>{self._median_table(cells, metrics)}</details>")
        return "".join(parts)

    def _median_table(self, cells, metrics):
        parts = ["<div class=scroll><table><tr><th class=row>metric</th>"
                 + "".join(f"<th>{escape(cell.config)}</th>" for cell in cells) + "</tr>",
                 "<tr><td class=row>usable runs</td>"
                 + "".join(f"<td>{len(cell.usable())}/{len(cell.runs)}</td>" for cell in cells) + "</tr>"]
        for metric in metrics:
            summaries = {cell.config: cell.summary(metric, self.confidence) for cell in cells}
            best = metric.best({config: summary["median"] for config, summary in summaries.items() if summary})
            parts.append(f"<tr><td class=row>{escape(metric.name)}</td>")
            for config, summary in summaries.items():
                parts.append(self._median(metric, summary, config in best))
            parts.append("</tr>")
        parts.append("</table></div>")
        return "".join(parts)

    def _median(self, metric, summary, best):
        if not summary:
            return "<td class=na>n/a</td>"

        title = f"n={summary['n']}"
        if summary["ci_low"] is not None:
            title += (f", {self.confidence:.0%} CI {metric.unit.format(summary['ci_low'])}"
                      f" – {metric.unit.format(summary['ci_high'])}")
        title += f", min {metric.unit.format(summary['min'])}, max {metric.unit.format(summary['max'])}"
        css = " class=best" if best else ""
        return f"<td{css} title='{escape(title)}'>{metric.unit.format(summary['median'])}</td>"

    @staticmethod
    def _csv(value):
        if value is None:
            return ""
        return f"{value:.10g}" if isinstance(value, float) else value
