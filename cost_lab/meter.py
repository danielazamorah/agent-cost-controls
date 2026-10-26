# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""TaskMeter: what ONE task really used, read from the usage_metadata on every model response.

"Price the task, not the token": one task = every model call and tool call it took to answer.
Attach it to any ADK LlmAgent with meter.attach(agent).
"""

import json


class TaskMeter:
    def __init__(self):
        self.reset()

    def reset(self):
        self.llm_calls = self.tool_calls = 0
        self.input_tokens = self.cached_tokens = self.thinking_tokens = self.output_tokens = 0
        self.cache_write_tokens = 0
        self.tool_payload_chars = 0

    def after_model(self, callback_context, llm_response):
        u = llm_response.usage_metadata
        if u is None:  # no usage reported: record nothing rather than a fake zero
            return None
        self.llm_calls += 1
        self.input_tokens += u.prompt_token_count or 0  # includes the cached tokens below
        self.cached_tokens += u.cached_content_token_count or 0  # served from cache, billed at a discount
        self.thinking_tokens += u.thoughts_token_count or 0  # billed as output
        self.output_tokens += u.candidates_token_count or 0
        self.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0  # Claude: writes cost extra
        return None

    def after_tool(self, tool, args, tool_context, tool_response):
        # Every tool result is appended to the history and re-sent on every later call of the task.
        self.tool_calls += 1
        self.tool_payload_chars += len(json.dumps(tool_response, default=str))
        return None

    def attach(self, agent):
        """Hooks this meter into an ADK agent; returns the meter so you can write meter = TaskMeter().attach(agent)."""
        agent.after_model_callback = self.after_model
        agent.after_tool_callback = self.after_tool
        return self

    def snapshot(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "cached_tokens": self.cached_tokens,
            "thinking_tokens": self.thinking_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "tool_payload_chars": self.tool_payload_chars,
        }
