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
    origin_kind: Literal["human", "ai", "collaborative", "unspecified"] = "unspecified"


class OwnerIdeaInput(IdeaInput):
    admission_reason: Short


class HumanRoleInput(StrictModel):
    role: Literal['user', 'admin']
    version: int = Field(ge=1, strict=True)
    reason: Short


class PromotionInput(StrictModel):
    promoted: bool
    reason: Short


class AgentQuestionInput(StrictModel):
    topic_id: str = Field(min_length=1, max_length=60)
    context_idea_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=5, max_length=160)
    body: str = Field(min_length=10, max_length=3000)
    human_input: str = Field(min_length=10, max_length=600)
    request_key: str = Field(min_length=16, max_length=80)


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


Role = Literal["summarizer", "challenger", "researcher", "bridge-builder", "catalyst-drafter", "claim-extractor"]


class TaskInput(StrictModel):
    question: Short
    role: Role = "researcher"
    tier: int = Field(default=2, ge=1, le=3, strict=True)
    success_criteria: str = Field(default="", max_length=600)


class ClaimInput(StrictModel):
    roles: list[Role] = Field(default_factory=lambda: ["summarizer", "challenger", "researcher", "bridge-builder", "catalyst-drafter", "claim-extractor"], min_length=1, max_length=6)


class SignalInput(StrictModel):
    topic_id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=5, max_length=160)
    body: str = Field(min_length=10, max_length=3000)
    origin_kind: Literal["human", "ai", "collaborative"] = "human"
    assistance: str = Field(default="", max_length=600)
    request_key: str | None = Field(default=None, min_length=16, max_length=80)


class QuestionReview(StrictModel):
    decision: Literal['awaiting-review', 'needs-clarification', 'declined']
    reason: Short
    expected_event: str = Field(default='', max_length=40)


class QuestionClarification(StrictModel):
    body: Short


class AgentQuestionReview(QuestionReview):
    decision: Literal['awaiting-review', 'needs-clarification', 'declined', 'answered']


class WorkerHeartbeat(StrictModel):
    runtime: Literal['simulation', 'external']
    model_label: str = Field(default='', max_length=120)
    state: Literal['connected', 'stopped', 'error'] = 'connected'


class TaskProgress(StrictModel):
    lease_token: str = Field(min_length=20, max_length=100)
    stage: Literal['preparing', 'generating', 'submitting', 'failed']
    sequence: int = Field(ge=1, le=10000, strict=True)
    excerpt: str = Field(default='', max_length=1200)


class SignalSupport(StrictModel):
    supported: bool


class DevelopSignal(StrictModel):
    kind: Literal["reflection", "catalyst", "claim"]
    summary: str = Field(min_length=10, max_length=1600)
    reason: Short


class TaskReview(StrictModel):
    verdict: Literal["useful", "revise", "not-useful"]
    reason: Short


class ResultInput(StrictModel):
    lease_token: str = Field(min_length=20, max_length=100)
    contribution: ContributionInput


class ReasonInput(StrictModel):
    reason: Short


class FeedbackInput(StrictModel):
    category: Literal["human-ux", "agent-ux", "content", "other"]
    body: Body


class AgentRegistration(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    purpose: str = Field(default='', max_length=600)


class AgentSettings(StrictModel):
    purpose: str = Field(default='', max_length=600)
    mode: Literal['automatic', 'queue-only']
    roles: list[Role] = Field(min_length=1, max_length=6)
    version: int = Field(ge=1, strict=True)
    allow_questions: bool = False


class AgentAction(StrictModel):
    action: Literal['pause', 'resume', 'retire']


class EnqueueWork(StrictModel):
    target_kind: Literal['idea', 'topic', 'task']
    target_id: str = Field(min_length=1, max_length=60)
    role: Role | None = None
    request_key: str = Field(min_length=16, max_length=80)


class QueueAction(StrictModel):
    action: Literal['next', 'remove']
