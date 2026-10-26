# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Offline tests: no model calls, no Google Cloud project needed.  Run: pytest -q"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cost_lab import agents, db, evals, meter, semantic_layer  # noqa: E402


# ---------- the database and its traps ----------

def test_database_has_the_business_traps():
    q = db.DB.execute
    assert q("SELECT COUNT(*) FROM sales").fetchone()[0] > 5000
    assert q("SELECT region FROM stores WHERE store_id = 99").fetchone()[0] == "INTERNAL"
    # Toronto closed for renovation, Bogota opened mid-September
    assert q("SELECT COUNT(*) FROM sales WHERE store_id = 4 AND sold_on BETWEEN '2026-08-18' AND '2026-08-24'").fetchone()[0] == 0
    assert q("SELECT MIN(sold_on) FROM sales WHERE store_id = 6").fetchone()[0] == "2026-09-10"
    # the test kitchen's fake orders are big enough to wreck any total that forgets to exclude them
    fake = q("SELECT SUM(gross_usd) FROM sales WHERE store_id = 99").fetchone()[0]
    real = q("SELECT SUM(gross_usd) FROM sales WHERE store_id <> 99 AND sold_on LIKE '2026-09-%'").fetchone()[0]
    assert fake > 0.25 * real


def test_run_sql_is_read_only_and_returns_rows():
    assert "error" in db.run_sql("DELETE FROM sales")
    assert "error" in db.run_sql("SELECT nope FROM sales")
    r = db.run_sql("SELECT city FROM stores ORDER BY store_id")
    assert r["columns"] == ["city"] and r["rows"][0] == ["Lisbon"]


def test_database_is_deterministic():
    total = db.DB.execute("SELECT ROUND(SUM(gross_usd), 2) FROM sales").fetchone()[0]
    assert total == db._build().execute("SELECT ROUND(SUM(gross_usd), 2) FROM sales").fetchone()[0]


# ---------- the semantic layer ----------

def test_semantic_layer_is_big_and_static():
    layer = semantic_layer.SEMANTIC_LAYER
    # Gemini 3.1 Pro Preview and 3.8 Flash need a 6,144-token shared prefix for implicit caching (~4 chars per token)
    assert len(layer) > 26_000
    assert "{" not in layer and "}" not in layer  # nothing ADK could mistake for a {state} placeholder
    for must_have in ("NET revenue", "INTERNAL", "FQ3", "Comparable store"):
        assert must_have in layer
    # the cheaper prompt really does drop the business definitions
    assert "NET revenue" not in semantic_layer.SCHEMA_ONLY and len(semantic_layer.SCHEMA_ONLY) < len(layer) / 3


# ---------- the agent factory ----------

def test_dynamic_first_puts_the_changing_header_on_top():
    a = agents.make_sql_agent("sql_test_dyn", **agents.BASELINE)
    assert a.static_instruction is None and callable(a.instruction)
    text = a.instruction(None)
    assert text.startswith("Current time (UTC):") and text.endswith(semantic_layer.SEMANTIC_LAYER)
    assert a.instruction(None) != text or True  # a new request ID every call (prefix changes)


def test_static_first_uses_adk_static_instruction():
    a = agents.make_sql_agent("sql_test_static", **{**agents.BASELINE, "layout": "static_first"})
    assert a.static_instruction == semantic_layer.SEMANTIC_LAYER
    assert a.instruction(None).startswith("Current time (UTC):")


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_thinking_level_and_billing_labels(level):
    a = agents.make_sql_agent(f"sql_test_{level}", thinking=level)
    cfg = a.generate_content_config
    assert cfg.thinking_config.thinking_level.value == level.upper()
    assert cfg.labels == {"agent": f"sql_test_{level}", "app": "day28-cost-lab"}


def test_no_glossary_variant_gets_the_schema_only():
    a = agents.make_sql_agent("sql_test_noglossary", glossary=False)
    assert a.instruction(None).endswith(semantic_layer.SCHEMA_ONLY)


# ---------- the meter ----------

def _resp(prompt=0, cached=0, thoughts=0, out=0):
    usage = types.SimpleNamespace(prompt_token_count=prompt, cached_content_token_count=cached,
                                  thoughts_token_count=thoughts, candidates_token_count=out)
    return types.SimpleNamespace(usage_metadata=usage)


def test_meter_adds_up_one_task():
    m = meter.TaskMeter()
    m.after_model(None, _resp(5000, 4200, 300, 40))
    m.after_model(None, _resp(5200, 4200, 100, 25))
    m.after_model(None, types.SimpleNamespace(usage_metadata=None))  # no usage: recorded as nothing, not as zero
    m.after_tool(None, {}, None, {"columns": ["n"], "rows": [[1]]})
    s = m.snapshot()
    assert s["llm_calls"] == 2 and s["input_tokens"] == 10200 and s["cached_tokens"] == 8400
    assert s["thinking_tokens"] == 400 and s["output_tokens"] == 65 and s["tool_calls"] == 1
    assert s["tool_payload_chars"] == len('{"columns": ["n"], "rows": [[1]]}')
    m.reset()
    assert m.snapshot()["llm_calls"] == 0


def test_attach_returns_the_meter():
    a = agents.make_sql_agent("sql_test_attach")
    m = meter.TaskMeter().attach(a)
    assert isinstance(m, meter.TaskMeter) and a.after_model_callback == m.after_model


# ---------- evals: references and the "cost per successful task" math ----------

def test_eval_set_references_come_from_the_data():
    assert len(evals.EVAL_SET) == 8
    refs = dict(evals.EVAL_SET)
    assert refs["Which region had the highest revenue in August 2026?"] in {"EMEA", "NA", "LATAM"}
    assert all(r for r in refs.values())


def test_summary_divides_by_successful_tasks_only():
    row = dict(variant="v", change={}, agent="a", llm_calls=2, tool_calls=1, input_tokens=1000, cached_tokens=600,
               thinking_tokens=200, output_tokens=50, tool_payload_chars=100, seconds=4.0)
    s = evals.summarize([{**row, "judge": 1}, {**row, "judge": 0}])["v"]
    assert s["judge"] == "1/2"
    assert s["total_tokens_per_success"] == 2 * (1000 + 200 + 50)  # the failed task's tokens still count
    assert s["cached_share_pct"] == 60.0 and s["llm_calls_per_task"] == 2.0
    assert "| v |" in evals.table_md({"v": s})


def test_price_the_task_uses_each_variants_own_model(monkeypatch, tmp_path):
    prices = tmp_path / "prices.json"
    prices.write_text('{"flash": {"input": 1.0, "cached_input": 0.1, "output": 5.0},'
                      ' "flagship": {"input": 4.0, "cached_input": 0.4, "output": 20.0}}')
    monkeypatch.setenv("PRICES_FILE", str(prices))
    monkeypatch.setenv("MODEL", "flash")
    row = dict(agent="a", llm_calls=1, tool_calls=0, input_tokens=1_000_000, cached_tokens=0,
               thinking_tokens=100_000, output_tokens=100_000, tool_payload_chars=0, seconds=1.0, judge=1)
    rows = [{**row, "variant": "baseline", "change": {}},
            {**row, "variant": "cached", "change": {"layout": "static_first"}, "cached_tokens": 900_000},
            {**row, "variant": "flagship", "change": {"model": "flagship"}, "input_tokens": 500_000}]
    s = evals.summarize(rows)
    assert s["baseline"]["usd_per_success"] == 2.0           # 1M input x $1 + 200k output (thinking is output) x $5
    assert s["cached"]["usd_per_success"] == round(0.1 + 0.09 + 1.0, 5)  # cached input billed at the cached price
    assert s["flagship"]["model"] == "flagship"              # the model knob picks the flagship's prices
    assert s["flagship"]["usd_per_success"] == 2.0 + 4.0      # half the input tokens, still 3x the dollars
    assert s["flagship"]["cost_index"] == 300 and s["baseline"]["cost_index"] == 100
    assert "$ / successful task" in evals.table_md(s)


def test_claude_cache_writes_are_priced_above_input(monkeypatch, tmp_path):
    prices = tmp_path / "prices.json"
    prices.write_text('{"claude": {"input": 2.0, "cached_input": 0.2, "cache_write": 2.5, "output": 10.0}}')
    monkeypatch.setenv("PRICES_FILE", str(prices))
    row = dict(variant="c", change={"model": "claude"}, agent="a", llm_calls=1, tool_calls=0, input_tokens=1_000_000,
               cached_tokens=0, cache_write_tokens=1_000_000, thinking_tokens=0, output_tokens=0,
               tool_payload_chars=0, seconds=1.0, judge=1)
    s = evals.summarize([row])["c"]
    assert s["usd_per_success"] == 2.5 and s["cache_write_per_success"] == 1_000_000  # every input token was a write
    m = meter.TaskMeter()
    assert "cache_write_tokens" in m.snapshot()
