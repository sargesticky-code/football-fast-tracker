from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SOURCES = ("FRB", "ACC", "BCL", "FST", "PRE", "STA")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--health-dir",
        type=Path,
        default=Path("multibetter/incoming/health"),
    )
    args = parser.parse_args()

    sources = {}
    for source in SOURCES:
        path = args.health_dir / f"{source.lower()}.json"
        if not path.exists():
            sources[source] = {
                "status": "MISSING_HEALTH",
                "rows": 0,
                "requests": 0,
                "errors": 1,
                "note": "Source step did not produce health metadata.",
            }
            continue
        try:
            sources[source] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            sources[source] = {
                "status": "INVALID_HEALTH",
                "rows": 0,
                "requests": 0,
                "errors": 1,
                "note": f"{type(exc).__name__}: {exc}",
            }

    summary = {
        "built_at_hkt": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(),
        "sources": sources,
        "fresh_optional_sources": [
            s for s in ("ACC", "BCL", "FST", "PRE", "STA")
            if sources[s].get("status") == "OK"
        ],
    }

    args.health_dir.mkdir(parents=True, exist_ok=True)
    (args.health_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))

    if sources["FRB"].get("status") != "OK":
        raise SystemExit("Forebet anchor is not fresh")


if __name__ == "__main__":
    main()
