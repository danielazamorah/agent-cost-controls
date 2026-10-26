# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Run the Day 28 cost lab with ADK's native telemetry going to Cloud Trace, Logging and Monitoring.

  python run_lab.py loop          # research_agent with a 40-call safety net vs RunConfig(max_llm_calls=8)
  python run_lab.py router        # a little cheap traffic, so the burn-rate view has several agents
  python run_lab.py experiments   # the analyst agent: baseline + one change at a time, judge next to the bill
  python run_lab.py experiments thinking_low static_first   # just some variants (merged into earlier results)
  python run_lab.py summary       # no model calls: re-price saved results with today's prices.json

Writes out/*.json and out/experiments_table.md with every number the episode shows.
"""

import asyncio
import json
import os
import pathlib
import sys
import uuid

HERE = pathlib.Path(__file__).parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE))

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
TELEMETRY_PROJECT = os.environ.get("TELEMETRY_PROJECT", PROJECT)  # e.g. models in one project, traces in another

# One baseline, then ONE change at a time (John DeMartino: "test one variable at a time" against a benchmark).
VARIANTS = {
    "baseline": {},
    "thinking_medium": {"thinking": "medium"},   # "Do you need high, or can you set it to medium or low...
    "thinking_low": {"thinking": "low"},         #  ...without degrading quality?"
    "static_first": {"layout": "static_first"},  # static semantic layer first, dynamic header last: cache hits
    "no_glossary": {"glossary": False},          # a cheaper prompt that quietly drops the business definitions
    "best": {"layout": "static_first", "thinking": "low"},  # combine the changes that held quality
    "model_argon": {"model": "gemini-4-argon"},  # same agent, one change: the flagship model
    "model_claude": {"model": "claude-sonnet-5-5"},  # same agent, one change: a partner model from Model Garden
}


def setup_telemetry() -> None:
    """Exactly what `adk web --otel_to_cloud` wires up: traces, logs and metrics to Google Cloud."""
    import google.auth
    from google.adk.telemetry.google_cloud import get_gcp_exporters, get_gcp_resource
    from google.adk.telemetry.setup import maybe_set_otel_providers
    from opentelemetry.sdk.resources import Resource

    credentials, _ = google.auth.default()
    hooks = get_gcp_exporters(enable_cloud_tracing=True, enable_cloud_metrics=True, enable_cloud_logging=True,
                              google_auth=(credentials, TELEMETRY_PROJECT))
    maybe_set_otel_providers(otel_hooks_to_setup=[hooks],
                             otel_resource=get_gcp_resource(TELEMETRY_PROJECT).merge(Resource.create({"service.name": "day28-cost-lab"})))


async def experiments(names: list[str]) -> None:
    from cost_lab.agents import BASELINE, make_sql_agent
    from cost_lab.evals import run_variant

    extra = {}  # combinations passed as name=knob:value,knob:value, e.g. best=layout:static_first,thinking:low
    for n in names:
        if "=" in n:
            label, spec = n.split("=", 1)
            extra[label] = {k: (v if v not in ("True", "False") else v == "True")
                            for k, v in (kv.split(":") for kv in spec.split(","))}
    variants = {**VARIANTS, **extra}
    todo = [n.split("=")[0] for n in names] or list(VARIANTS)
    rows_file = OUT / "experiments_rows.json"
    rows = [r for r in (json.load(open(rows_file)) if rows_file.exists() and names else []) if r["variant"] not in todo]
    for name in todo:
        change = variants[name]
        agent = make_sql_agent(f"sql_{name}", **{**BASELINE, **change})
        rows += await run_variant(name, agent, change)
        json.dump(rows, open(rows_file, "w"), indent=1)  # save as we go
    order = list(variants)
    rows.sort(key=lambda r: order.index(r["variant"]) if r["variant"] in order else len(order))
    json.dump(rows, open(rows_file, "w"), indent=1)
    write_summary(rows)


def write_summary(rows: list[dict]) -> None:
    from cost_lab.evals import summarize, table_md

    summary = summarize(rows)
    json.dump(summary, open(OUT / "experiments_summary.json", "w"), indent=1)
    (OUT / "experiments_table.md").write_text(table_md(summary) + "\n")
    print(table_md(summary))


def summary_only() -> None:
    """Price the saved tasks again (e.g. after the pricing page changes) without calling any model."""
    write_summary(json.load(open(OUT / "experiments_rows.json")))


async def loop(_names) -> None:
    from google.adk.agents.run_config import RunConfig
    from cost_lab.agents import research_agent
    from cost_lab.evals import ask
    from cost_lab.meter import TaskMeter

    meter = TaskMeter().attach(research_agent)
    out = {}
    for label, cap in (("unbounded_safety_net_40", 40), ("bounded_8", 8)):
        meter.reset()
        r = await ask(research_agent, "Prepare the Q3 market briefing for leadership.",
                      run_config=RunConfig(max_llm_calls=cap), user=f"loop-{label}")
        out[label] = {**r, "max_llm_calls": cap, **meter.snapshot()}
        print(label, json.dumps(out[label])[:400], flush=True)
    json.dump(out, open(OUT / "loop.json", "w"), indent=1)


async def router(_names) -> None:
    from cost_lab.agents import router_agent
    from cost_lab.evals import EVAL_SET, ask

    texts = [q for q, _ in EVAL_SET] + ["Prepare the Q3 market briefing.", "What's the weather?"]
    res = [await ask(router_agent, t, user="router") for t in texts]
    json.dump(res, open(OUT / "router.json", "w"), indent=1)
    print("router done", [r["answer"] for r in res])


def main():
    what, names = (sys.argv[1] if len(sys.argv) > 1 else "experiments"), sys.argv[2:]
    if what == "summary":
        return summary_only()
    if not PROJECT:
        sys.exit("Set GOOGLE_CLOUD_PROJECT (and GOOGLE_CLOUD_LOCATION=global, GOOGLE_GENAI_USE_VERTEXAI=true).")
    setup_telemetry()
    print("run", uuid.uuid4().hex[:6], "model", os.environ.get("MODEL", "gemini-3.8-flash"), flush=True)
    for w in (["router", "loop", "experiments"] if what == "all" else [what]):
        asyncio.run(globals()[w](names))
    from opentelemetry import metrics, trace
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    mp = metrics.get_meter_provider()
    if hasattr(mp, "force_flush"):
        mp.force_flush()


if __name__ == "__main__":
    main()
