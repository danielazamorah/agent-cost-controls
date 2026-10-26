# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Agents for the Day 28 cost lab.

- research_agent: told to wait for a report that never finishes (the runaway loop).
- router_agent: a cheap classifier, so the burn-rate view has more than one agent.
- make_sql_agent(): the analyst agent, built from one BASELINE plus ONE change at a time.

Every model call carries billing labels, so Cloud Billing can split spend per agent.
"""

import os
import uuid
from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig, ThinkingConfig

from .db import run_sql
from .semantic_layer import SCHEMA_ONLY, SEMANTIC_LAYER
from .tools import check_report_status

MODEL = os.environ.get("MODEL", "gemini-3.8-flash")
LITE_MODEL = os.environ.get("LITE_MODEL", "gemini-3.1-flash-lite")


def cfg(agent: str, thinking_level: str | None = None, max_output_tokens: int | None = None,
        model: str | None = None) -> GenerateContentConfig:
    if model and model.startswith("claude"):
        # Claude on Agent Platform: same knob, Anthropic's names. Adaptive thinking, depth set by `effort`.
        from google.adk.models.anthropic_llm import AnthropicGenerateContentConfig
        return AnthropicGenerateContentConfig(
            effort=thinking_level.lower() if thinking_level else None,
            thinking_config=ThinkingConfig(thinking_budget=-1) if thinking_level else None,
            max_output_tokens=max_output_tokens,
        )
    return GenerateContentConfig(
        labels={"agent": agent, "app": "day28-cost-lab"},  # lands in the Cloud Billing export
        thinking_config=ThinkingConfig(thinking_level=thinking_level.upper()) if thinking_level else None,
        max_output_tokens=max_output_tokens,
    )


# ---------------- the runaway loop and a cheap router ----------------

research_agent = LlmAgent(
    name="research_agent",
    model=MODEL,
    instruction=(
        "You prepare the quarterly market briefing. The briefing MUST be based on the q3-market report. "
        "Call check_report_status('q3-market') and keep checking until its status is READY. "
        "Never answer before the report is READY."
    ),
    tools=[check_report_status],
    generate_content_config=cfg("research_agent"),
)

router_agent = LlmAgent(
    name="router_agent",
    model=LITE_MODEL,
    instruction="Classify the user's request as SALES_QUESTION, REPORT_REQUEST or OTHER. Reply with the label only.",
    generate_content_config=cfg("router_agent", max_output_tokens=16),
)


# ---------------- the analyst agent: one baseline, one change at a time ----------------

def request_header(ctx) -> str:
    """Per-request context many agents put in their prompt: the time, a request ID and who is asking."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"Current time (UTC): {now}. Request ID: {uuid.uuid4().hex[:12]}. Caller: finance analyst (read-only).\n\n"


BASELINE = {"layout": "dynamic_first", "thinking": "high", "glossary": True, "model": None}


def make_sql_agent(name: str, layout: str = "dynamic_first", thinking: str = "high", glossary: bool = True,
                   model: str | None = None) -> LlmAgent:
    """The same analyst agent with four knobs: prompt layout, thinking level, semantic layer, and the model."""
    layer = SEMANTIC_LAYER if glossary else SCHEMA_ONLY
    model_id = model or MODEL
    llm = model_id
    if model_id.startswith("claude"):  # partner models from Model Garden: one line, through ADK's model classes
        from google.adk.models.anthropic_llm import Claude
        llm = Claude(model=model_id)
    common = dict(name=name, model=llm, tools=[run_sql],
                  generate_content_config=cfg(name, thinking_level=thinking, model=model_id))
    if layout == "static_first":
        # ADK sends static_instruction first and unchanged on every call, then adds `instruction` after it.
        # A long, identical prefix is what caching needs (implicit: 6,144+ tokens on Gemini 3.8 Flash).
        return LlmAgent(static_instruction=layer, instruction=request_header, **common)
    # dynamic_first: one instruction with the per-request header on top, so every request starts differently.
    return LlmAgent(instruction=lambda ctx: request_header(ctx) + layer, **common)
