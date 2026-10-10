"""Compare the deployed dashboard's stored closes with Yahoo's latest rows.

Exit 0 when every ticker the site serves is as current as Yahoo for that
ticker, 1 when at least one is behind, 2 when a source could not be read.
Only completed sessions count: before 17:30 WIB (close 16:00 plus Yahoo's
usual EOD lag) today's still-forming bar is ignored, so a healthy site never
looks behind during the trading day. Stdlib only, so the workflow can run it
before installing the model stack.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

JAKARTA = ZoneInfo("Asia/Jakarta")
EXPECTED_CLOSE = (17, 30)
USER_AGENT = "Mozilla/5.0 (compatible; prog5-freshness-guard)"
DEFAULT_SITE = "https://pokonya-lulus.vercel.app"


def _get_json(url: str, attempts: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(1 + attempt)
    raise RuntimeError(f"could not read {url}: {last_error}")


def stored_dates(base_url: str) -> dict[str, date | None]:
    """Newest stored close per ticker as the site serves it."""
    payload = _get_json(f"{base_url.rstrip('/')}/api/v1/stocks")
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected /api/v1/stocks payload: {type(payload).__name__}")
    return {
        row["symbol"]: date.fromisoformat(row["last_price_date"])
        if row.get("last_price_date")
        else None
        for row in payload
    }


def yahoo_latest(symbol: str, now: datetime | None = None) -> date | None:
    """Newest completed-session close Yahoo offers for one IDX ticker."""
    payload = _get_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.JK"
        "?range=10d&interval=1d"
    )
    chart = payload.get("chart") or {}
    results = chart.get("result")
    if not results:
        return None  # symbol error from Yahoo: nothing to demand for it
    stamps = results[0].get("timestamp") or []
    closes = ((results[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    days = [
        datetime.fromtimestamp(stamp, JAKARTA).date()
        for stamp, close in zip(stamps, closes)
        if close is not None
    ]
    moment = now or datetime.now(JAKARTA)
    cutoff = moment.replace(hour=EXPECTED_CLOSE[0], minute=EXPECTED_CLOSE[1], second=0, microsecond=0)
    if moment < cutoff:
        days = [day for day in days if day < moment.date()]
    return max(days) if days else None


def verdicts(stored: dict[str, date | None], latest: dict[str, date | None]) -> list[str]:
    """Tickers whose stored close trails what Yahoo offers for that ticker."""
    behind = []
    for symbol in sorted(stored):
        offered = latest.get(symbol)
        have = stored[symbol]
        if offered is not None and (have is None or have < offered):
            behind.append(symbol)
    return behind


def evaluate(stored: dict[str, date | None], latest: dict[str, date | None]) -> tuple[str, int]:
    """Print per-ticker verdicts and return (verdict line, exit code).

    A ticker with no Yahoo frame at all can never be matched, so it fails the
    check: a Yahoo outage must not look like a healthy site. A stored close
    more than one completed session behind Yahoo is reported with its own
    verdict line so the workflow that calls this fails loudly rather than
    skipping a refresh that was actually needed.
    """
    missing_yahoo = sorted(symbol for symbol, offered in latest.items() if offered is None)
    behind = verdicts(stored, latest)
    for symbol in sorted(stored):
        have = stored[symbol]
        offered = latest.get(symbol)
        state = "behind" if symbol in behind else "fresh"
        print(f"{symbol:5s} stored={have or 'none'!s:10s} yahoo={offered or 'none'!s:10s} {state}")
    if missing_yahoo:
        print(f"no Yahoo rows: {','.join(missing_yahoo)}")
    if behind:
        print(f"verdict=behind tickers={len(stored)} behind={','.join(behind)}")
        return "verdict=behind", 1
    if missing_yahoo:
        print(f"verdict=behind tickers={len(stored)} behind={','.join(missing_yahoo)}")
        return "verdict=behind", 1
    print(f"verdict=fresh tickers={len(stored)}")
    return "verdict=fresh", 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PROG5_SITE_URL", DEFAULT_SITE),
        help="deployed site origin (default: PROG5_SITE_URL or the production URL)",
    )
    args = parser.parse_args(argv)
    try:
        stored = stored_dates(args.base_url)
        if not stored:
            raise RuntimeError("the site serves no tickers at all")
        latest = {symbol: yahoo_latest(symbol) for symbol in stored}
    except Exception as error:
        print(f"freshness check unreadable: {error}", file=sys.stderr)
        return 2

    _, code = evaluate(stored, latest)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
