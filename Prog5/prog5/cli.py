"""Command line entry points: refresh, verify, inventory, serve."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__, config


def _horizons(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(",") if part.strip())


def _symbols(value: str) -> tuple[str, ...]:
    return tuple(part.strip().upper() for part in value.split(",") if part.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prog5", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="fetch EOD data and store predictions")
    refresh.add_argument("--symbols", required=True, type=_symbols)
    refresh.add_argument("--horizons", type=_horizons, default=config.HORIZONS)
    refresh.add_argument("--period", default=config.DEFAULT_HISTORY_PERIOD)

    verify = sub.add_parser("verify", help="reproduce the committed research result CSVs")
    verify.add_argument("--symbols", type=_symbols, default=config.SUPPORTED_SYMBOLS)
    verify.add_argument("--horizons", type=_horizons, default=config.HORIZONS)

    sub.add_parser("inventory", help="show resolvable artifacts per ticker")

    snapshot = sub.add_parser("import-snapshot", help="copy a SQLite snapshot to the configured database")
    snapshot.add_argument("--sqlite-path", required=True)

    serve = sub.add_parser("serve", help="run the read-only API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    schedule = sub.add_parser("schedule", help="run the unattended refresh")
    schedule.add_argument(
        "--once",
        action="store_true",
        help="check the clock once and exit (for Task Scheduler probes)",
    )
    schedule.add_argument(
        "--force",
        action="store_true",
        help="run once now even when no scheduled slot is due (implies --once)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)

    if args.command == "refresh":
        from .refresh import RefreshInProgress, refresh

        try:
            report = refresh(args.symbols, horizons=args.horizons, period=args.period)
        except RefreshInProgress as error:
            print(f"refresh skipped: {error}")
            return 2
        print(report.to_text())
        return 0 if report.status == "completed" else 1

    if args.command == "verify":
        from .replication import verify

        mismatches = 0
        for symbol in args.symbols:
            for row in verify(symbol, args.horizons):
                print(
                    f"{row['symbol']:6s} T{row['horizon_days']:<3d} rows={row['rows']:<5d} "
                    f"max|diff|={row['max_abs_diff']:.6f} IDR  {row['verdict']}"
                )
                mismatches += row["verdict"] != "reproduced"
        print(f"{'ALL REPRODUCED' if not mismatches else f'{mismatches} MISMATCHES'}")
        return 1 if mismatches else 0

    if args.command == "inventory":
        from .model_registry import artifact_inventory

        for symbol, count in artifact_inventory().items():
            print(f"{symbol:6s} {count}/{len(config.HORIZONS)} artifacts")
        return 0

    if args.command == "import-snapshot":
        from .snapshot import import_snapshot

        counts = import_snapshot(args.sqlite_path)
        for table, count in counts.items():
            print(f"{table}: {count} source rows processed")
        return 0

    if args.command == "schedule":
        from .scheduler import run_forever, run_scheduled

        if args.once or args.force:
            outcome = run_scheduled(force=args.force)
            print(outcome.to_text())
            return outcome.exit_code()
        run_forever()
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run("prog5.api:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
