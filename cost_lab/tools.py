# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
"""The research agent's tool: a quarterly report that never finishes generating (the runaway loop)."""

from google.adk.tools import ToolContext


def check_report_status(report_id: str, tool_context: ToolContext) -> dict:
    """Checks whether the quarterly market report has finished generating.

    Args:
        report_id: The report to check, for example "q3-market".
    """
    # The report never becomes ready in this demo, so an agent told to "keep checking" never stops.
    n = tool_context.state.get("status_checks", 0) + 1
    tool_context.state["status_checks"] = n
    return {"report_id": report_id, "status": "PENDING", "progress": "generating", "checks_so_far": n}
