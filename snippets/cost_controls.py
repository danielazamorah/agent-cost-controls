# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""Day 28 in one file: five cost controls on one ADK agent.  Run from the repo root:  python snippets/cost_controls.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.context_cache_config import ContextCacheConfig  # noqa: E402
from google.adk.agents.invocation_context import LlmCallsLimitExceededError  # noqa: E402
from google.adk.agents.run_config import RunConfig  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from cost_lab.db import run_sql  # noqa: E402
from cost_lab.semantic_layer import SEMANTIC_LAYER  # noqa: E402  (about 8.5k tokens of schema + glossary)

usage = {"calls": 0, "input": 0, "cached": 0, "thinking": 0, "output": 0}


def meter(callback_context, llm_response):  # 1. Meter every model call: price the task, not the token
    u = llm_response.usage_metadata
    if u:
        usage["calls"] += 1
        usage["input"] += u.prompt_token_count or 0
        usage["cached"] += u.cached_content_token_count or 0
        usage["thinking"] += u.thoughts_token_count or 0
        usage["output"] += u.candidates_token_count or 0


agent = LlmAgent(
    name="sql_analyst",
    model="gemini-3.8-flash",
    tools=[run_sql],
    static_instruction=SEMANTIC_LAYER,  # 2. The static part first, identical on every call: cacheable
    instruction="Caller: finance analyst (read-only).",  # the dynamic part goes after it
    generate_content_config=types.GenerateContentConfig(
        labels={"agent": "sql_analyst"},  # 3. A billing label: spend per agent in Cloud Billing
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),  # 4. Right-size the reasoning
    ),
    after_model_callback=meter,
)
app = App(name="cost_controls", root_agent=agent,
          context_cache_config=ContextCacheConfig(min_tokens=4096, ttl_seconds=600))


async def main():
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name="cost_controls", user_id="me")
    for question in ["What was revenue in September 2026 across all stores?", "And in August 2026?"]:
        try:
            async for event in runner.run_async(
                    user_id="me", session_id=session.id,
                    run_config=RunConfig(max_llm_calls=8),  # 5. A hard iteration bound (the default is 500)
                    new_message=types.Content(role="user", parts=[types.Part(text=question)])):
                if event.is_final_response() and event.content and event.content.parts:
                    print(question, "->", event.content.parts[0].text)
        except LlmCallsLimitExceededError:  # the bound was hit: answer politely instead of looping
            print(question, "-> Sorry, that took too many steps. Try a narrower question.")
        print("   so far:", usage)
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
