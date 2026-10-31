"""Thin MCP transport; the run supervisor owns all state and provider processes."""

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

loader = SourceFileLoader(
    "review_client", str(Path(__file__).with_name("agent-review"))
)
spec = importlib.util.spec_from_loader(loader.name, loader)
client = importlib.util.module_from_spec(spec)
loader.exec_module(client)
mcp = FastMCP("cross-review", log_level="WARNING")


@mcp.tool()
def review_start(
    request_id: str,
    brief: Annotated[
        str,
        Field(
            description="Path to an existing UTF-8 brief file, NOT its text. Write it under /runs/artifacts, e.g. /runs/artifacts/review-brief.md."
        ),
    ],
    kind: str = "research",
    base: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    one_shot: bool = False,
) -> dict:
    """Start the opposite-provider reviewer. brief is a FILE PATH; include names evidence paths, exclude names repository glob patterns. Poll review_events and answer questions."""
    params = {
        "request_id": request_id,
        "brief": brief,
        "kind": kind,
        "include": include or [],
        "exclude": exclude or [],
        "one_shot": one_shot,
    }
    if base:
        params["base"] = base
    return client.call("run", params)


@mcp.tool()
def review_reply(review_id: str, request_id: str, reply_to: str, message: dict) -> dict:
    """Answer the pending message. message: answers[{question_id,answer,evidence}], questions[], include[]."""
    return client.call(
        "reply",
        {
            "review_id": review_id,
            "request_id": request_id,
            "reply_to": reply_to,
            "message": message,
        },
    )


@mcp.tool()
def review_recheck(
    review_id: str,
    request_id: str,
    response: dict,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict:
    """Use round 2 after fixes/rebuttal. response: responses[{finding_id,action,reason,evidence}]."""
    params = {"review_id": review_id, "request_id": request_id, "response": response}
    if include is not None:
        params["include"] = include
    if exclude is not None:
        params["exclude"] = exclude
    return client.call("recheck", params)


@mcp.tool()
def review_status(review_id: str) -> dict:
    """Read state, verdict and applicability without starting a model turn; remaining counts are null (unlimited)."""
    return client.call("status", {"review_id": review_id})


@mcp.tool()
def review_events(review_id: str, after: int = 0, wait_seconds: float = 20) -> dict:
    """Read messages after a cursor; bounded wait yields control so the worker can reply."""
    return client.call(
        "events", {"review_id": review_id, "after": after, "wait_seconds": wait_seconds}
    )


@mcp.tool()
def review_cancel(review_id: str, request_id: str) -> dict:
    """Cancel a running or waiting review; preserve its partial transcript."""
    return client.call("cancel", {"review_id": review_id, "request_id": request_id})


@mcp.tool()
def review_extend(
    review_id: str, request_id: str, max_rounds: int | None = None,
    reason: str = "", user_requested: bool = False
) -> dict:
    """Legacy compatibility operation: review rounds are unlimited and require no extension."""
    return client.call(
        "extend",
        {
            "review_id": review_id,
            "request_id": request_id,
            "max_rounds": max_rounds,
            "reason": reason,
            "user_requested": user_requested,
        },
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
