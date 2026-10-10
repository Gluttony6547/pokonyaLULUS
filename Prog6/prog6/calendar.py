"""One calendar, two packages: Prog6 imports, never re-implements.

Prog5's trading_calendar already encodes weekend rules plus the IDX 2026/2027
holiday tables. Importing means a holiday-table update lands once.
"""

from prog5.trading_calendar import (  # noqa: F401
    add_trading_days,
    holidays_for_year,
    is_trading_day,
    lands_on_unverified_session,
    next_trading_day,
    target_date,
)

__all__ = [
    "add_trading_days",
    "holidays_for_year",
    "is_trading_day",
    "lands_on_unverified_session",
    "next_trading_day",
    "target_date",
]
