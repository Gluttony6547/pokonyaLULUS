"""Run the Prog6 pipeline against the configured Prog5 database.

Usage: python scripts/refresh_local.py [--symbols ADRO,...] [--horizons 1,5,...]
No network access happens here; closes come from the tables Prog5's refresh
pipeline already maintains.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prog6.refresh import SYMBOLS, refresh  # noqa: E402

HORIZONS = (1, 5, 10, 20, 50)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--horizons", default=",".join(map(str, HORIZONS)))
    args = parser.parse_args()

    symbols = tuple(part.strip().upper() for part in args.symbols.split(",") if part.strip())
    horizons = tuple(int(part) for part in args.horizons.split(",") if part.strip())
    reports = refresh(symbols, horizons)
    failures = 0
    for report in reports:
        metrics = "; ".join(
            f"T{b.horizon} {b.policy} {b.metrics.to_text()}" for b in report.backtests
        )
        print(f"{report.symbol}: predictions={report.predictions} {metrics}")
        for error in report.errors:
            print(f"  ERROR {error}")
            failures += 1
    return 1 if failures and not any(r.predictions for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
