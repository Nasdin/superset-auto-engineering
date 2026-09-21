"""Validate report-only automation handoffs; never publish audit findings publicly."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_complete: StrictBool
    summary: str = Field(min_length=1, max_length=12000)
    observations: list[str] = Field(max_length=20)
    blocker: str = Field(max_length=4000)


def finish_review(store, job, result):
    try:
        report = ReviewResult.model_validate(result)
    except ValidationError:
        raise ValueError("Review handoff is invalid or incomplete") from None
    if not report.task_complete:
        raise ValueError("Review has no final handoff")
    store.commit_handoff(
        job["id"],
        values={
            "state": "needs_attention" if report.blocker else "completed",
            "result": report.model_dump(),
            "error": report.blocker or None,
        },
    )
