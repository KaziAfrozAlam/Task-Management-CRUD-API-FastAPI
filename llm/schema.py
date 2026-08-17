from pydantic import BaseModel, Field
from enum import Enum


class Category(str, Enum):
    billing = "billing"
    bug = "bug"
    feature = "feature"
    account = "account"
    other = "other"


class Urgency(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Team(str, Enum):
    billing = "billing"
    engineering = "engineering"
    product = "product"
    support = "support"


class TriageInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class TriageOutput(BaseModel):
    category: Category
    urgency: Urgency
    suggested_team: Team
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str