# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Day 28: the metadata-aware SQL analyst, deployed to Cloud Run with Layer 2 and Layer 3 caps."""
import os

from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig, ThinkingConfig

from .tools import SCHEMA, run_sql

root_agent = LlmAgent(
    name="sql_analyst",
    model=os.environ.get("MODEL", "gemini-3.8-flash"),
    static_instruction=(  # the static part first: identical on every call, so it can be cached
        f"You answer sales questions over this SQLite schema:\n{SCHEMA}\n"
        "Write one query with run_sql, then answer with the number and a short sentence. "
        "Only run another query if the first one returned an error."
    ),
    tools=[run_sql],
    generate_content_config=GenerateContentConfig(
        labels={"agent": "sql_analyst", "app": "day28-cost-lab"},  # billing labels (Gemini on Agent Platform)
        thinking_config=ThinkingConfig(thinking_level="LOW"),  # Gemini 3 uses thinking levels, not budgets
    ),
)
