"""Match-quality reports: pipelines/territory/sources/reports/<source_key>_match_report.md."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).resolve().parent / "sources" / "reports"


def write_match_report(source_key: str, *, fetched: int, matched: int, unmatched: int,
                       methods: Counter, examples: list[dict[str, Any]],
                       notes: dict[str, Any], signals_written: int,
                       report_dir: Path | None = None) -> Path:
    d = report_dir or REPORT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{source_key}_match_report.md"
    lines = [
        f"# Match report: {source_key}",
        "",
        f"Generated {datetime.now().isoformat(timespec='seconds')}",
        "",
        "| Measure | Count |",
        "|---|---|",
        f"| Rows fetched (in territory scope, stored in raw_records) | {fetched} |",
        f"| Matched to a parcel | {matched} |",
        f"| Unmatched | {unmatched} |",
        f"| Signals written (new rows) | {signals_written} |",
        "",
        "## Match method breakdown",
        "",
    ]
    if methods:
        lines += ["| Method | Rows |", "|---|---|"]
        lines += [f"| {m} | {n} |" for m, n in sorted(methods.items())]
    else:
        lines.append("No rows matched.")
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {k}: {v}" for k, v in notes.items()]
    lines += ["", "## Example unmatched rows (max 10, no personal data)", ""]
    if examples:
        for e in examples[:10]:
            lines.append("- " + ", ".join(f"{k}={v}" for k, v in e.items()))
    else:
        lines.append("None.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
