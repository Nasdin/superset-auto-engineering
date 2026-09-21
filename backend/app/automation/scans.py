"""Validate final scan handoffs before an empty finding list can mean success."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    base_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    reproduction: str = Field(min_length=1)
    acceptance: str = Field(min_length=1)


class ScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_complete: StrictBool
    findings: list[Finding] = Field(max_length=1)
    summary: str = Field(min_length=1, max_length=12000)
    # Pre-catalogue sessions did not include blocker in their requested schema.
    blocker: str = Field(default="", max_length=4000)
