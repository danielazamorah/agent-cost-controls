# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""A small, realistic sales database for a cafe chain (SQLite, in memory, deterministic).

Tables: stores, products, sales (one row per store / product / day / channel), refunds.
The data has the usual business traps a semantic layer exists for: an internal test kitchen
that must be excluded, discounts and refunds (revenue means NET revenue), a fiscal calendar,
a store that closed for a week, and a store that opened mid-September.
"""

import datetime as dt
import random
import sqlite3

STORES = [  # store_id, city, country, region, opened_on, status
    (1, "Lisbon", "Portugal", "EMEA", "2023-03-01", "open"),
    (2, "Madrid", "Spain", "EMEA", "2024-11-15", "open"),
    (3, "Austin", "United States", "NA", "2022-06-01", "open"),
    (4, "Toronto", "Canada", "NA", "2025-12-01", "open"),
    (5, "Mexico City", "Mexico", "LATAM", "2021-09-01", "open"),
    (6, "Bogota", "Colombia", "LATAM", "2026-09-10", "open"),
    (99, "Test Kitchen", "United States", "INTERNAL", "2020-01-01", "internal"),
]

PRODUCTS = [  # product_id, sku, name, category, list_price_usd
    (1, "COF-ESP", "espresso", "coffee", 3.00),
    (2, "COF-CBR", "cold brew", "coffee", 4.50),
    (3, "COF-OLL", "cafe de olla", "coffee", 2.50),
    (4, "COF-FLW", "flat white", "coffee", 4.25),
    (5, "COF-COR", "cortado", "coffee", 3.50),
    (6, "PAS-NAT", "pastel de nata", "pastry", 2.00),
    (7, "PAS-CHU", "churros", "pastry", 3.00),
    (8, "PAS-BTT", "butter tart", "pastry", 3.00),
    (9, "PAS-CON", "concha", "pastry", 1.50),
    (10, "FOO-BTA", "breakfast taco", "food", 4.00),
    (11, "FOO-TOS", "tostada", "food", 3.75),
    (12, "FOO-CRS", "croissant sandwich", "food", 6.50),
]

MENU = {  # store_id -> (product_id, typical units per day)
    1: [(1, 70), (4, 45), (6, 120), (12, 25)],
    2: [(1, 60), (5, 40), (7, 90), (12, 20)],
    3: [(2, 80), (4, 35), (10, 85), (12, 30)],
    4: [(2, 40), (4, 50), (8, 55), (12, 22)],
    5: [(3, 95), (1, 30), (9, 140), (11, 45)],
    6: [(1, 35), (3, 50), (9, 60), (11, 25)],
}
CHANNEL_SHARE = {"in_store": 0.62, "delivery": 0.23, "app": 0.15}
FIRST_DAY, LAST_DAY = dt.date(2026, 8, 1), dt.date(2026, 10, 21)  # data is loaded through Oct 21, 2026
TORONTO_RENOVATION = (dt.date(2026, 8, 18), dt.date(2026, 8, 24))


def _build() -> sqlite3.Connection:
    rng = random.Random(28)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.executescript(
        """
CREATE TABLE stores (store_id INTEGER PRIMARY KEY, city TEXT, country TEXT, region TEXT, opened_on TEXT, status TEXT);
CREATE TABLE products (product_id INTEGER PRIMARY KEY, sku TEXT, name TEXT, category TEXT, list_price_usd REAL);
CREATE TABLE sales (sale_id INTEGER PRIMARY KEY, store_id INTEGER, product_id INTEGER, sold_on TEXT, channel TEXT,
                    units INTEGER, gross_usd REAL, discount_usd REAL);
CREATE TABLE refunds (refund_id INTEGER PRIMARY KEY, sale_id INTEGER, refunded_on TEXT, amount_usd REAL, reason TEXT);
"""
    )
    db.executemany("INSERT INTO stores VALUES (?,?,?,?,?,?)", STORES)
    db.executemany("INSERT INTO products VALUES (?,?,?,?,?)", PRODUCTS)
    price = {p[0]: p[4] for p in PRODUCTS}
    category = {p[0]: p[3] for p in PRODUCTS}
    opened = {s[0]: dt.date.fromisoformat(s[4]) for s in STORES}
    sales, refunds = [], []
    day = FIRST_DAY
    while day <= LAST_DAY:
        weekend = day.weekday() >= 5
        for store_id, items in MENU.items():
            if day < opened[store_id]:
                continue
            if store_id == 4 and TORONTO_RENOVATION[0] <= day <= TORONTO_RENOVATION[1]:
                continue
            for product_id, base in items:
                for channel, share in CHANNEL_SHARE.items():
                    units = max(0, round(base * share * (1.25 if weekend else 1.0) * rng.uniform(0.75, 1.25)))
                    if units == 0:
                        continue
                    gross = round(units * price[product_id], 2)
                    # "Pastry Tuesday": 20% off pastries on Tuesdays in September
                    promo = day.month == 9 and day.weekday() == 1 and category[product_id] == "pastry"
                    discount = round(gross * 0.20, 2) if promo else 0.0
                    sales.append((len(sales) + 1, store_id, product_id, day.isoformat(), channel, units, gross, discount))
                    if rng.random() < 0.03:  # about 3% of rows get a (partial) refund, up to 14 days later
                        when = min(day + dt.timedelta(days=rng.randint(0, 14)), LAST_DAY)
                        amount = round((gross - discount) * rng.choice([0.1, 0.25, 0.5, 1.0]), 2)
                        refunds.append((len(refunds) + 1, len(sales), when.isoformat(), amount,
                                        rng.choice(["wrong order", "quality", "late delivery", "duplicate charge"])))
        day += dt.timedelta(days=1)
    # QA load tests in the internal Test Kitchen (must never show up in reporting)
    for d, product_id, units in (("2026-09-14", 1, 4000), ("2026-09-15", 1, 6000), ("2026-09-16", 1, 5000)):
        sales.append((len(sales) + 1, 99, product_id, d, "app", units, round(units * price[product_id], 2), 0.0))
        refunds.append((len(refunds) + 1, len(sales), d, round(units * price[product_id], 2), "test transaction"))
    db.executemany("INSERT INTO sales VALUES (?,?,?,?,?,?,?,?)", sales)
    db.executemany("INSERT INTO refunds VALUES (?,?,?,?,?)", refunds)
    db.commit()
    return db


DB = _build()


def run_sql(query: str) -> dict:
    """Runs one read-only SQLite query against the cafe chain's sales database. Returns up to 50 rows.

    Args:
        query: A single SELECT (or WITH ... SELECT) statement in SQLite syntax.
    """
    if not query.strip().lower().startswith(("select", "with")):
        return {"error": "Only SELECT queries are allowed."}
    try:
        cur = DB.execute(query)
        cols = [c[0] for c in cur.description]
        return {"columns": cols, "rows": [list(r) for r in cur.fetchmany(50)]}
    except Exception as e:  # the model sees the error and can fix its query
        return {"error": str(e)}
