# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Tools for the Day 28 Cloud Run SQL analyst service."""

import sqlite3

_DB = sqlite3.connect(":memory:", check_same_thread=False)
_DB.executescript(
    """
CREATE TABLE stores (store_id INTEGER PRIMARY KEY, city TEXT, region TEXT);
CREATE TABLE sales (sale_id INTEGER PRIMARY KEY, store_id INTEGER, month TEXT, product TEXT, units INTEGER, revenue_usd REAL);
INSERT INTO stores VALUES (1,'Lisbon','EMEA'),(2,'Madrid','EMEA'),(3,'Austin','NA'),(4,'Toronto','NA'),(5,'Mexico City','LATAM');
INSERT INTO sales (store_id, month, product, units, revenue_usd) VALUES
 (1,'2026-08','espresso',420,1260.0),(1,'2026-08','pastel de nata',900,1800.0),(1,'2026-09','espresso',460,1380.0),(1,'2026-09','pastel de nata',870,1740.0),
 (2,'2026-08','espresso',380,1140.0),(2,'2026-08','churros',640,1920.0),(2,'2026-09','espresso',410,1230.0),(2,'2026-09','churros',700,2100.0),
 (3,'2026-08','cold brew',520,2340.0),(3,'2026-08','breakfast taco',610,2440.0),(3,'2026-09','cold brew',480,2160.0),(3,'2026-09','breakfast taco',650,2600.0),
 (4,'2026-08','cold brew',300,1350.0),(4,'2026-08','butter tart',410,1230.0),(4,'2026-09','cold brew',260,1170.0),(4,'2026-09','butter tart',450,1350.0),
 (5,'2026-08','cafe de olla',700,1750.0),(5,'2026-08','concha',980,1470.0),(5,'2026-09','cafe de olla',760,1900.0),(5,'2026-09','concha',1020,1530.0);
"""
)

SCHEMA = """stores(store_id INTEGER PRIMARY KEY, city TEXT, region TEXT)  -- regions: EMEA, NA, LATAM
sales(sale_id INTEGER PRIMARY KEY, store_id INTEGER REFERENCES stores, month TEXT 'YYYY-MM', product TEXT, units INTEGER, revenue_usd REAL)"""


def run_sql(query: str) -> dict:
    """Runs a read-only SQLite query against the sales database and returns up to 20 rows.

    Args:
        query: A single SELECT statement.
    """
    if not query.strip().lower().startswith(("select", "with")):
        return {"error": "Only SELECT queries are allowed."}
    try:
        cur = _DB.execute(query)
        cols = [c[0] for c in cur.description]
        return {"columns": cols, "rows": [list(r) for r in cur.fetchmany(20)]}
    except Exception as e:  # the model sees the error and can retry
        return {"error": str(e)}
