"""Reference data: the ten supported tickers and the IDX holiday calendar.

Both live in the database so they can be updated as data. These constants are
the first-run seed and the offline fallback when no database is reachable.
"""

from __future__ import annotations

from datetime import date

# Names and sectors are the issuers' public identities; the tickers are the ten
# the reference research trained on.
STOCKS: tuple[tuple[str, str, str], ...] = (
    ("ADRO", "Adaro Energy Indonesia Tbk", "Energy"),
    ("ANTM", "Aneka Tambang Tbk", "Basic Materials"),
    ("BMRI", "Bank Mandiri (Persero) Tbk", "Financials"),
    ("BNGA", "Bank CIMB Niaga Tbk", "Financials"),
    ("EXCL", "XL Axiata Tbk", "Communication Services"),
    ("INCO", "Vale Indonesia Tbk", "Basic Materials"),
    ("INKP", "Indah Kiat Pulp & Paper Tbk", "Basic Materials"),
    ("MEDC", "Medco Energi Internasional Tbk", "Energy"),
    ("PGAS", "Perusahaan Gas Negara Tbk", "Utilities"),
    ("TLKM", "Telkom Indonesia (Persero) Tbk", "Communication Services"),
)

# Weekday closures only: weekends are already covered by the weekend rule.
# Taken from IDX's published trading holiday calendar.
MARKET_HOLIDAYS: tuple[date, ...] = (
    date(2026, 1, 1),    # Tahun Baru
    date(2026, 1, 16),   # Isra Mikraj
    date(2026, 2, 16),   # Cuti bersama Imlek
    date(2026, 2, 17),   # Tahun Baru Imlek
    date(2026, 3, 18),   # Nyepi
    date(2026, 3, 19),   # Cuti bersama Nyepi
    date(2026, 3, 20),   # Idul Fitri
    date(2026, 3, 23),   # Idul Fitri
    date(2026, 3, 24),   # Cuti bersama Idul Fitri
    date(2026, 4, 3),    # Wafat Isa Almasih
    date(2026, 5, 1),    # Hari Buruh
    date(2026, 5, 14),   # Kenaikan Isa Almasih
    date(2026, 5, 27),   # Idul Adha
    date(2026, 5, 28),   # Cuti bersama Idul Adha
    date(2026, 6, 1),    # Hari Lahir Pancasila
    date(2026, 6, 16),   # Tahun Baru Islam
    date(2026, 8, 17),   # Hari Kemerdekaan
    date(2026, 8, 25),   # Maulid Nabi
    date(2026, 12, 24),  # Cuti bersama Natal
    date(2026, 12, 25),  # Hari Natal
    date(2026, 12, 31),  # Hari Bursa Tutup Tahun
    date(2027, 1, 1),
    date(2027, 1, 5),
    date(2027, 2, 5),
    date(2027, 3, 9),
    date(2027, 3, 10),
    date(2027, 3, 11),
    date(2027, 3, 12),
    date(2027, 3, 26),
    date(2027, 5, 6),
    date(2027, 5, 17),
    date(2027, 5, 18),
    date(2027, 5, 20),
    date(2027, 6, 1),
    date(2027, 8, 17),
    date(2027, 12, 31),
)
