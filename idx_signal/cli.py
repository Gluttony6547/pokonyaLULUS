"""Command line entry points: refresh, verify, register, serve, schedule, train."""

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
    parser = argparse.ArgumentParser(prog="idx-signal", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    refresh_parser = sub.add_parser("refresh", help="fetch EOD data and store fresh signals")
    refresh_parser.add_argument("--symbols", type=_symbols, default=config.SUPPORTED_SYMBOLS)
    refresh_parser.add_argument("--horizons", type=_horizons, default=config.HORIZONS)
    refresh_parser.add_argument("--period", default=config.DEFAULT_HISTORY_PERIOD)

    register_parser = sub.add_parser("register", help="record the saved artifacts as model versions")
    register_parser.add_argument("--symbols", type=_symbols, default=config.SUPPORTED_SYMBOLS)
    register_parser.add_argument("--horizons", type=_horizons, default=config.HORIZONS)

    verify_parser = sub.add_parser("verify", help="reproduce the committed research predictions")
    verify_parser.add_argument("--symbols", type=_symbols, default=config.SUPPORTED_SYMBOLS)
    verify_parser.add_argument("--horizons", type=_horizons, default=config.HORIZONS)

    sub.add_parser("inventory", help="show resolvable artifacts per ticker")
    sub.add_parser("seed", help="create tables and seed tickers and holidays")

    serve = sub.add_parser("serve", help="run the dashboard and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    schedule = sub.add_parser("schedule", help="run the unattended data update")
    schedule.add_argument("--once", action="store_true", help="check the clock once and exit")
    schedule.add_argument("--force", action="store_true", help="run now even when no slot is due")

    worker = sub.add_parser("train-worker", help="run queued training jobs")
    worker.add_argument("--once", action="store_true", help="run at most one job and exit")
    worker.add_argument("--poll-seconds", type=int, default=15)

    train = sub.add_parser("train", help="queue a training run and wait for it")
    train.add_argument("--symbol", required=True)
    train.add_argument("--horizon", type=int, required=True)
    train.add_argument("--force", action="store_true", help="retrain even when a model exists")
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
        return 0 if report.status in {"success", "partial"} else 1

    if args.command == "register":
        from . import db
        from .refresh import ensure_model_versions
        from .storage import ensure_reference_data

        db.init_db()
        with db.session() as session:
            ensure_reference_data(session)
            versions = ensure_model_versions(session, args.symbols, args.horizons, refresh_metrics=True)
        for (symbol, horizon), version in sorted(versions.items()):
            metrics = version.metrics or {}
            accuracy = metrics.get("accuracy")
            print(
                f"{symbol:6s} T{horizon:<3d} version={version.id:<5d} "
                f"accuracy={accuracy if accuracy is not None else 'n/a'} "
                f"sha256={version.artifact_sha256[:12]}"
            )
        return 0

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
        print("ALL REPRODUCED" if not mismatches else f"{mismatches} MISMATCHES")
        return 1 if mismatches else 0

    if args.command == "inventory":
        from .model_registry import artifact_inventory

        for symbol, count in artifact_inventory().items():
            print(f"{symbol:6s} {count}/{len(config.HORIZONS)} artifacts")
        return 0

    if args.command == "seed":
        from . import db
        from .storage import ensure_reference_data

        db.init_db()
        with db.session() as session:
            ensure_reference_data(session)
        print(f"seeded {len(config.SUPPORTED_SYMBOLS)} tickers and the holiday calendar")
        return 0

    if args.command == "schedule":
        from .scheduler import run_forever, run_scheduled

        if args.once or args.force:
            outcome = run_scheduled(force=args.force)
            print(outcome.to_text())
            return outcome.exit_code()
        run_forever()
        return 0

    if args.command == "train-worker":
        from .training import run_queued_once, run_worker_forever

        if args.once:
            ran = run_queued_once()
            print("ran one job" if ran else "queue empty")
            return 0
        run_worker_forever(args.poll_seconds)
        return 0

    if args.command == "train":
        from . import db
        from .training import queue_training_job, run_job
        from .storage import ensure_reference_data

        db.init_db()
        with db.session() as session:
            ensure_reference_data(session)
            job, existing = queue_training_job(
                session, args.symbol.upper(), args.horizon, force=args.force
            )
            if job is None:
                print(
                    f"{args.symbol} T{args.horizon} already has active model version "
                    f"{existing.id if existing else '?'}; nothing queued (use --force to retrain)."
                )
                return 0
            job_id = job.id
        finished = run_job(job_id)
        if finished is None:
            print(f"training job {job_id} disappeared")
            return 1
        print(
            f"training job {job_id} status={finished.status} "
            f"model_version={finished.model_version_id} error={finished.error_message}"
        )
        return 0 if finished.status == "success" else 1

    if args.command == "serve":
        import uvicorn

        uvicorn.run("idx_signal.api:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
