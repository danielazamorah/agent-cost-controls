# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Evaluate agent variants with BOTH views: the judge's verdict next to what each task cost.

- EVAL_SET: 8 analyst questions. Reference answers are computed from the database, not typed by hand.
- judge(): LLM-as-a-judge, PASS or FAIL against the reference.
- run_variant(): one analyst chat session per variant (the 8 questions in a row), with a TaskMeter attached.
  ADK's context cache is ON for every variant; only a stable prompt prefix can actually use it.
- summarize(): John DeMartino's unit, "cost per successful task": total tokens divided by passed tasks.
"""

import asyncio
import json
import os
import pathlib
import time

from .db import DB, LAST_DAY
from .meter import TaskMeter

_NOT_INTERNAL = "JOIN stores st ON st.store_id = s.store_id WHERE st.region <> 'INTERNAL'"


def _net_revenue_sql(where: str) -> str:
    return f"""WITH scoped AS (SELECT s.sale_id, s.gross_usd, s.discount_usd FROM sales s
               JOIN stores st ON st.store_id = s.store_id JOIN products p ON p.product_id = s.product_id
               WHERE st.region <> 'INTERNAL' AND {where})
               SELECT SUM(gross_usd) - SUM(discount_usd)
                      - COALESCE((SELECT SUM(amount_usd) FROM refunds WHERE sale_id IN (SELECT sale_id FROM scoped)), 0)
               FROM scoped"""


def _money(v):
    return f"${v:,.2f}"


def _units(v):
    return f"{int(v):,} units"


def _pct(v):
    return f"{v:.1f}%"


def _region_with_top_revenue(month: str) -> str:
    rows = [(r, DB.execute(_net_revenue_sql(f"st.region = '{r}' AND s.sold_on LIKE '{month}-%'")).fetchone()[0])
            for r in ("EMEA", "NA", "LATAM")]
    return max(rows, key=lambda x: x[1])[0]


EVAL_SET = [
    ("What was revenue in September 2026 across all stores?",
     lambda: _money(DB.execute(_net_revenue_sql("s.sold_on LIKE '2026-09-%'")).fetchone()[0])),
    ("How many units of cold brew did we sell in August 2026?",
     lambda: _units(DB.execute(f"SELECT SUM(s.units) FROM sales s {_NOT_INTERNAL} AND s.product_id = 2 "
                               "AND s.sold_on LIKE '2026-08-%'").fetchone()[0])),
    ("Which region had the highest revenue in August 2026?",
     lambda: _region_with_top_revenue("2026-08")),
    ("What is Lisbon's revenue for Q3 so far?",
     lambda: _money(DB.execute(_net_revenue_sql(
         f"st.city = 'Lisbon' AND s.sold_on BETWEEN '2026-08-01' AND '{LAST_DAY.isoformat()}'")).fetchone()[0])),
    ("How many pastry units did we sell in September 2026?",
     lambda: _units(DB.execute(f"SELECT SUM(s.units) FROM sales s {_NOT_INTERNAL} AND s.product_id IN "
                               "(SELECT product_id FROM products WHERE category = 'pastry') "
                               "AND s.sold_on LIKE '2026-09-%'").fetchone()[0])),
    ("What was revenue from breakfast tacos in Austin in September 2026?",
     lambda: _money(DB.execute(_net_revenue_sql(
         "st.city = 'Austin' AND p.name = 'breakfast taco' AND s.sold_on LIKE '2026-09-%'")).fetchone()[0])),
    ("What share of the units we sold in September 2026 went through delivery?",
     lambda: _pct(DB.execute(f"SELECT 100.0 * SUM(CASE WHEN s.channel = 'delivery' THEN s.units ELSE 0 END) "
                             f"/ SUM(s.units) FROM sales s {_NOT_INTERNAL} AND s.sold_on LIKE '2026-09-%'").fetchone()[0])),
    ("What was our refund rate in September 2026?",
     lambda: _pct(DB.execute(
         "WITH scoped AS (SELECT s.sale_id, s.gross_usd FROM sales s JOIN stores st ON st.store_id = s.store_id "
         "WHERE st.region <> 'INTERNAL' AND s.sold_on LIKE '2026-09-%') SELECT 100.0 * COALESCE((SELECT SUM(amount_usd) "
         "FROM refunds WHERE sale_id IN (SELECT sale_id FROM scoped)), 0) / SUM(gross_usd) FROM scoped").fetchone()[0])),
]
EVAL_SET = [(q, ref()) for q, ref in EVAL_SET]  # references come from the data itself

JUDGE_PROMPT = """You are grading a data analyst's answer.
Question: {q}
Reference answer: {ref}
Analyst answer: {a}
The answer is correct if it gives the same number or entity as the reference. Formatting and rounding
differences are fine (a dollar amount within $1, a percentage within 0.1 points). Anything else is wrong.
Reply with exactly PASS or FAIL."""


_JUDGE_CLIENT = None


def judge(q: str, ref: str, answer: str) -> int:
    global _JUDGE_CLIENT
    from google import genai

    if _JUDGE_CLIENT is None:  # keep a reference: a client that gets garbage collected closes its connection
        _JUDGE_CLIENT = genai.Client()
    r = _JUDGE_CLIENT.models.generate_content(
        model=os.environ.get("JUDGE_MODEL", "gemini-3.8-flash"),
        contents=JUDGE_PROMPT.format(q=q, ref=ref, a=answer or "(no answer)"))
    return 1 if (r.text or "").strip().upper().startswith("PASS") else 0


async def ask(agent, text: str, user: str = "eval-user", run_config=None, runner=None, session_id=None) -> dict:
    """One task: the question goes in, the final answer comes out. Pass runner + session_id to continue a chat."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    own = runner is None
    if own:
        runner = InMemoryRunner(agent=agent, app_name="day28_cost_lab")
    if session_id is None:
        session_id = (await runner.session_service.create_session(app_name=runner.app_name, user_id=user)).id
    final, error, t0 = "", None, time.time()
    try:
        async for ev in runner.run_async(user_id=user, session_id=session_id, run_config=run_config,
                                         new_message=types.Content(role="user", parts=[types.Part(text=text)])):
            if ev.is_final_response() and ev.content and ev.content.parts:
                final = "".join(p.text or "" for p in ev.content.parts if not getattr(p, "thought", False))
    except Exception as e:  # e.g. LlmCallsLimitExceededError when a RunConfig cap is hit
        error = f"{type(e).__name__}: {e}"
    if own:
        await runner.close()
    return {"answer": final.strip(), "error": error, "seconds": round(time.time() - t0, 1), "session_id": session_id}


def make_runner(agent):
    """Every variant runs in the same app setup: ADK's context cache is ON for all of them.

    ADK can only reuse a cache when the start of the request (system instruction + tools) is identical
    from call to call. A per-request header at the top of the instruction changes that every time.
    """
    from google.adk.agents.context_cache_config import ContextCacheConfig
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner

    app = App(name="day28_cost_lab", root_agent=agent,
              context_cache_config=ContextCacheConfig(min_tokens=4096, ttl_seconds=600, cache_intervals=20))
    return InMemoryRunner(app=app)


async def run_variant(name: str, agent, change: dict) -> list[dict]:
    """One analyst session per variant: the 8 questions are asked in a row, like a real chat."""
    meter = TaskMeter().attach(agent)
    runner = make_runner(agent)
    user = f"eval-{name}"
    session_id = (await runner.session_service.create_session(app_name=runner.app_name, user_id=user)).id
    rows = []
    for q, ref in EVAL_SET:
        meter.reset()
        r = await ask(agent, q, user=user, runner=runner, session_id=session_id)
        score = await asyncio.to_thread(judge, q, ref, r["answer"])
        rows.append({"variant": name, "change": change, "agent": agent.name, "question": q, "reference": ref,
                     "model": getattr(agent.model, "model", agent.model), **r, "judge": score, **meter.snapshot()})
        m = rows[-1]
        print(f"[{name}] judge={score} calls={m['llm_calls']} in={m['input_tokens']} cached={m['cached_tokens']} "
              f"think={m['thinking_tokens']} out={m['output_tokens']} {m['seconds']}s :: {m['answer'][:80]!r}", flush=True)
    await runner.close()
    return rows


def _prices():
    """Optional: prices.json with per-1M-token prices from the official pricing page, to turn tokens into dollars."""
    p = pathlib.Path(os.environ.get("PRICES_FILE", pathlib.Path(__file__).parent.parent / "prices.json"))
    return json.loads(pathlib.Path(p).read_text()) if pathlib.Path(p).exists() else None


def model_of(row: dict) -> str:
    """The model a task ran on: recorded on the row, or the variant's model knob, or the default MODEL."""
    return row.get("model") or row["change"].get("model") or os.environ.get("MODEL", "gemini-3.8-flash")


def task_usd(tot: dict, price: dict) -> float:
    """Price the task: uncached input + cached input (discounted) + output, where thinking is billed as output."""
    writes = tot.get("cache_write_tokens", 0)  # Anthropic prompt-cache writes cost more than plain input
    return ((tot["input_tokens"] - tot["cached_tokens"] - writes) * price["input"]
            + writes * price.get("cache_write", price["input"])
            + tot["cached_tokens"] * price["cached_input"]
            + (tot["thinking_tokens"] + tot["output_tokens"]) * price["output"]) / 1e6


def summarize(rows: list[dict]) -> dict:
    out = {}
    prices = _prices()
    for name in dict.fromkeys(r["variant"] for r in rows):
        rs = [r for r in rows if r["variant"] == name]
        n, passed = len(rs), sum(r["judge"] for r in rs)
        tot = {k: sum(r.get(k, 0) for r in rs) for k in ("llm_calls", "tool_calls", "input_tokens", "cached_tokens",
                                                          "cache_write_tokens", "thinking_tokens", "output_tokens",
                                                          "tool_payload_chars", "seconds")}
        per_success = (lambda k, tot=tot, passed=passed: round(tot[k] / passed) if passed else None)
        s = {
            "change": rs[0]["change"], "agent": rs[0]["agent"], "tasks": n, "passed": passed,
            "judge": f"{passed}/{n}",
            # John's unit: cost per SUCCESSFUL task (failed tasks still cost money)
            "input_per_success": per_success("input_tokens"),
            "cached_per_success": per_success("cached_tokens"),
            "cache_write_per_success": per_success("cache_write_tokens"),
            "thinking_per_success": per_success("thinking_tokens"),
            "output_per_success": per_success("output_tokens"),
            "total_tokens_per_success": (round((tot["input_tokens"] + tot["thinking_tokens"] + tot["output_tokens"]) / passed)
                                         if passed else None),
            "cached_share_pct": round(100 * tot["cached_tokens"] / tot["input_tokens"], 1) if tot["input_tokens"] else 0.0,
            "llm_calls_per_task": round(tot["llm_calls"] / n, 2),
            "tool_payload_chars_per_task": round(tot["tool_payload_chars"] / n),
            "seconds_per_task": round(tot["seconds"] / n, 1),
        }
        s["model"] = model_of(rs[0])
        if prices and passed and s["model"] in prices:
            s["usd_per_success"] = round(task_usd(tot, prices[s["model"]]) / passed, 5)
        out[name] = s
    base = out.get("baseline", {}).get("usd_per_success")
    for s in out.values():  # dollars relative to the baseline (= 100), so the comparison survives price changes
        if base and s.get("usd_per_success"):
            s["cost_index"] = round(100 * s["usd_per_success"] / base)
    return out


def table_md(summary: dict) -> str:
    priced = any("usd_per_success" in s for s in summary.values())
    cols = ["variant", "change", "judge", "tokens / successful task", "of which cached", "thinking", "calls / task",
            "sec / task"] + (["$ / successful task", "cost index"] if priced else [])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for name, s in summary.items():
        change = ", ".join(f"{k}={v}" for k, v in s["change"].items()) or "(baseline)"
        line = (f"| {name} | {change} | {s['judge']} | {s['total_tokens_per_success'] or '-':,} | "
                f"{s['cached_per_success'] or 0:,} ({s['cached_share_pct']}%) | {s['thinking_per_success'] or 0:,} | "
                f"{s['llm_calls_per_task']} | {s['seconds_per_task']} |")
        if priced:
            line += f" {s.get('usd_per_success', '-')} | {s.get('cost_index', '-')} |"
        lines.append(line)
    return "\n".join(lines)
