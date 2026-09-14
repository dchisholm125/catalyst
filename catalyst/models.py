"""The contribution contract rejects extra fields, including forged identities."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Short = Annotated[str, Field(min_length=1, max_length=600)]
Body = Annotated[str, Field(min_length=1, max_length=6000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Impact(StrictModel):
    reach: Literal["unassessed", "local", "community", "regional", "global"] = "unassessed"
    depth: Literal["unassessed", "limited", "material", "transformative"] = "unassessed"
    confidence: Literal["speculative", "argued", "tested", "demonstrated"] = "speculative"
    explanation: Short = "Potential impact has not been independently evaluated."
    burdens: Short = "Not yet assessed."


class Dissent(StrictModel):
    contribution_id: str = Field(min_length=1, max_length=40)
    explanation: Short
    disposition: Literal["open", "addressed", "retained"] = "open"
    rationale: Short


class Synthesis(StrictModel):
    summary: str = Field(min_length=1, max_length=1600)
    principles: list[Short] = Field(default_factory=list, max_length=12)
    dissent: list[Dissent] = Field(default_factory=list, max_length=100)
    questions: list[Short] = Field(default_factory=list, max_length=12)
    impact: Impact = Field(default_factory=Impact)


class IdeaInput(StrictModel):
    title: str = Field(min_length=5, max_length=160)
    kind: Literal["reflection", "catalyst", "claim"]
    origin: Body
    synthesis: Synthesis


class ContributionInput(StrictModel):
    kind: Literal["observation", "objection", "evidence", "question", "response"]
    body: Body
    parent_id: str | None = Field(default=None, max_length=40)
    provenance: str = Field(default="", max_length=1000)


class DraftInput(StrictModel):
    base_id: str = Field(min_length=1, max_length=40)
    reason: Short
    synthesis: Synthesis


class ReviewInput(StrictModel):
    decision: Literal["publish", "reject"]
    reason: Short


class ReactionInput(StrictModel):
    revision_id: str = Field(min_length=1, max_length=40)
    worth: int = Field(ge=-1, le=1, strict=True)
    stance: Literal["agree", "uncertain", "disagree"]
    explore: bool


class BudgetInput(StrictModel):
    share: int = Field(ge=0, le=100, strict=True)
    daily_jobs: int = Field(ge=0, le=20, strict=True)
    enabled: bool


class TaskInput(StrictModel):
    question: Short


class ResultInput(StrictModel):
    lease_token: str = Field(min_length=20, max_length=100)
    contribution: ContributionInput


class ReasonInput(StrictModel):
    reason: Short


class FeedbackInput(StrictModel):
    category: Literal["human-ux", "agent-ux", "content", "other"]
    body: Body
