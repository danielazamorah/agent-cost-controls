# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Which agent is consuming the most tokens? Runs sql/burn_rate_by_agent.sql in BigQuery and saves the rows.

  python burn_rate.py            # last 24 hours (the SQL file's window)
  python burn_rate.py 3          # last 3 hours

Needs the Cloud Trace _Trace bucket linked to BigQuery as dataset `agent_spans` (Observability Analytics).
"""

import json
import os
import pathlib
import sys

from google.cloud import bigquery

HERE = pathlib.Path(__file__).parent
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]


def main():
    sql = (HERE / "sql" / "burn_rate_by_agent.sql").read_text().replace("YOUR_PROJECT", PROJECT)
    if len(sys.argv) > 1:
        sql = sql.replace("INTERVAL 24 HOUR", f"INTERVAL {int(sys.argv[1])} HOUR")
    rows = [dict(r) for r in bigquery.Client(project=PROJECT).query(sql).result()]
    (HERE / "out").mkdir(exist_ok=True)
    json.dump(rows, open(HERE / "out" / "burn_rate.json", "w"), indent=1, default=str)
    for r in rows:
        print(f"{r['agent_name']:22s} {r['model']:24s} sessions={r['sessions']:>3} calls/session={r['llm_calls_per_session']:>5} "
              f"input/session={r['input_tokens_per_session']:>8} thinking%={r['thinking_pct']}")


if __name__ == "__main__":
    main()
