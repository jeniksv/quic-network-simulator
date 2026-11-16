"""CSV tables and an HTML report of a matrix."""
import csv
import html

SUMMARY_COLUMNS = ("n", "median", "ci_low", "ci_high", "p25", "p75", "min", "max", "mean", "sd")


def write_runs_csv(path, runs, metrics):
    """One row per run: identity, whether h2load.json was parsed, and every metric."""
    with open(path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["scenario", "workload", "config", "repetition", "run", "error",
                         *[metric.name for metric in metrics]])
        for run in runs:
            values = [_csv(run.metrics[m.name]) if run.metrics else "" for m in metrics]
            writer.writerow([run.scenario, run.workload, run.config, run.repetition, run.name,
                             run.error or "", *values])


def write_cells_csv(path, cells, metrics, confidence):
    """One row per cell and metric: numbers of runs and the distribution over the runs."""
    with open(path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["scenario", "workload", "config", "runs", "usable_runs", "metric", *SUMMARY_COLUMNS])
        for key in sorted(cells):
            cell = cells[key]
            usable = len(cell.usable())
            for metric in metrics:
                summary = cell.summary(metric, confidence) or {}
                writer.writerow([*key, len(cell.runs), usable, metric.name,
                                 *[_csv(summary.get(column)) for column in SUMMARY_COLUMNS]])


def _csv(value):
    if value is None:
        return ""
    return f"{value:.10g}" if isinstance(value, float) else value


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


def write_html(path, title, info, runs, cells, metrics, confidence):
    configs = sorted({run.config for run in runs})
    out = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width, initial-scale=1'>"
           f"<title>{_e(title)}</title><style>{STYLE}</style></head><body><h1>{_e(title)}</h1>",
           "<p>" + "<br>".join(_e(line) for line in info) + "</p>",
           "<h2>Runs</h2>", _runs_table(runs, configs), _failed_runs(runs),
           "<h2>Medians per scenario and workload</h2>",
           f"<p class=muted>One row per metric and one column per configuration: the median over the "
           f"usable runs of the cell; the best configuration is bold. Hover for the number of runs, the {confidence:.0%} confidence interval of the median "
           f"(at least 6 runs) and the extremes.</p>"]
    for group in sorted({cell.group for cell in cells.values()}):
        out.append(f"<h3>{_e(group[0])} / {_e(group[1])}</h3>")
        out.append(_median_table(group, configs, metrics, cells, confidence))
    out.append("<h2>Metrics</h2><ul>")
    for metric in metrics:
        notes = [f"{metric.better} is better" if metric.better else "no direction"]
        if metric.unit:
            notes.append(metric.unit)
        out.append(f"<li><b>{_e(metric.name)}</b> ({_e(', '.join(notes))}): {_e(metric.description)}</li>")
    out.append("</ul></body></html>")
    path.write_text("\n".join(out))


def _runs_table(runs, configs):
    parts = ["<table><tr><th class=row>configuration</th><th>runs</th><th>usable</th>"
             "<th>without h2load.json</th></tr>"]
    for config in configs:
        own = [run for run in runs if run.config == config]
        usable = sum(run.metrics is not None for run in own)
        parts.append(f"<tr><td class=row>{_e(config)}</td><td>{len(own)}</td><td>{usable}</td>"
                     f"<td>{len(own) - usable}</td></tr>")
    parts.append("</table>")
    return "".join(parts)


def _failed_runs(runs):
    failed = [run for run in runs if run.metrics is None]
    if not failed:
        return "<p class=muted>Every run has a usable h2load.json.</p>"
    parts = [f"<details><summary>Runs without a usable h2load.json ({len(failed)})</summary>"
             "<div class=scroll><table><tr><th class=row>run</th><th class=row>reason</th></tr>"]
    for run in failed:
        parts.append(f"<tr><td class=row>{_e(run.name)}</td><td class=row>{_e(run.error)}</td></tr>")
    parts.append("</table></div></details>")
    return "".join(parts)


def _median_table(group, configs, metrics, cells, confidence):
    """Medians of one scenario and workload: one row per metric, one column per configuration."""
    group_cells = {config: cells[(*group, config)] for config in configs if (*group, config) in cells}
    parts = ["<div class=scroll><table><tr><th class=row>metric</th>"
             + "".join(f"<th>{_e(config)}</th>" for config in group_cells) + "</tr>",
             "<tr><td class=row>usable runs</td>"
             + "".join(f"<td>{len(cell.usable())}/{len(cell.runs)}</td>" for cell in group_cells.values())
             + "</tr>"]
    for metric in metrics:
        summaries = {config: cell.summary(metric, confidence) for config, cell in group_cells.items()}
        best = _best(metric, summaries)
        parts.append(f"<tr><td class=row>{_e(metric.name)}</td>")
        for config, summary in summaries.items():
            if not summary:
                parts.append("<td class=na>n/a</td>")
                continue
            title = f"n={summary['n']}"
            if summary["ci_low"] is not None:
                title += (f", {confidence:.0%} CI {_value(summary['ci_low'], metric)}"
                          f" – {_value(summary['ci_high'], metric)}")
            title += f", min {_value(summary['min'], metric)}, max {_value(summary['max'], metric)}"
            css = " class=best" if config in best else ""
            parts.append(f"<td{css} title='{_e(title)}'>{_value(summary['median'], metric)}</td>")
        parts.append("</tr>")
    parts.append("</table></div>")
    return "".join(parts)


def _best(metric, summaries):
    """Configurations with the best median; none when all of them are equal or the metric has no direction."""
    medians = {config: summary["median"] for config, summary in summaries.items() if summary}
    if metric.better is None or len(set(medians.values())) < 2:
        return set()
    top = (max if metric.better == "higher" else min)(medians.values())
    return {config for config, value in medians.items() if value == top}


def _value(value, metric):
    if metric.unit == "bit/s":
        return f"{value / 1e6:.2f} Mbit/s"
    if metric.unit == "s":
        return f"{value * 1e3:.1f} ms" if abs(value) < 10 else f"{value:.2f} s"
    if metric.unit == "B/s":
        return f"{value / 1e6:.2f} MB/s"
    if metric.unit in ("packets", "datagrams", "requests", "responses", "clients", "bytes"):
        return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"
    if metric.unit == "1/s":
        return f"{value:.2f}/s"
    return f"{value:.3f}"


def _e(text):
    return html.escape(str(text), quote=True)
