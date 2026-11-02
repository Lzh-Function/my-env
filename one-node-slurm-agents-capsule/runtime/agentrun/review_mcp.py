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
    reviewers: Annotated[list[str] | None, Field(
        description="Other providers to ask: codex, claude, antigravity. Omitted means the opposite of Codex/Claude.")] = None,
    models: Annotated[dict[str, str] | None, Field(
        description="Reviewer model per provider, e.g. {\"codex\": \"<id from review_models>\"}.")] = None,
    efforts: Annotated[dict[str, str] | None, Field(
        description="Reasoning effort per provider; must be listed for the chosen model. Omit for Antigravity.")] = None,
    model_source: Annotated[str | None, Field(
        description="'user' only when the user explicitly named the model/effort; otherwise 'agent'.")] = None,
) -> dict:
    """Start reviews with other providers (codex, claude, antigravity). reviewers selects one or more; multiple targets return reviews[]. Call review_models first and choose models/efforts unless the user specified them or the response shows a configured value. brief is a FILE PATH; include names evidence paths, exclude names repository glob patterns. Poll and answer each review independently."""
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
    for key, value in (("reviewers", reviewers), ("models", models), ("efforts", efforts),
                       ("model_source", model_source)):
        if value is not None:
            params[key] = value
    return client.call("run", params)


@mcp.tool()
def review_models(reviewers: list[str] | None = None, refresh: bool = False) -> dict:
    """List models each reviewer CLI currently offers (id, name, description, supported efforts) and any user-configured model. Lists change with CLI updates; never rely on memorized names. The first call may take minutes while the reviewer CLI is installed."""
    params = {"refresh": refresh}
    if reviewers is not None:
        params["reviewers"] = reviewers
    return client.call("models", params, timeout=900)


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
    brief: Annotated[str | None, Field(
        description="Optional new brief FILE PATH, e.g. for the next task reviewed in the same conversation.")] = None,
    base: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    model: str | None = None,
    effort: str | None = None,
    model_source: str | None = None,
) -> dict:
    """Start the next round after fixes/rebuttal, or ask the same reviewer about new work with a new brief/include. response: responses[{finding_id,action,reason,evidence}] for every previous finding. model/effort default to the previous round's choice."""
    params = {"review_id": review_id, "request_id": request_id, "response": response}
    for key, value in (("brief", brief), ("base", base), ("include", include), ("exclude", exclude),
                       ("model", model), ("effort", effort), ("model_source", model_source)):
        if value is not None:
            params[key] = value
    return client.call("recheck", params)


@mcp.tool()
def review_retry(review_id: str, request_id: str, model: str | None = None, effort: str | None = None,
                 model_source: str | None = None) -> dict:
    """Retry the same round after a failure that names recovery (invalid_model, authentication, rate_limit, timeout, provider errors); pass a model from review_models after invalid_model. Use a fresh request_id; the snapshot and pending reply are retained, so no new review_start is needed."""
    params = {"review_id": review_id, "request_id": request_id}
    for key, value in (("model", model), ("effort", effort), ("model_source", model_source)):
        if value is not None:
            params[key] = value
    return client.call("retry", params)


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
