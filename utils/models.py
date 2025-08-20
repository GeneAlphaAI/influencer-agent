from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime


# -----------------------
# Tweet
# -----------------------
class SummaryModel(BaseModel):
    is_prediction: bool
    token: Optional[str] = None
    predicted_price: Optional[float] = None
    currency: Optional[str] = None
    percent_change: Optional[float] = None
    direction: Optional[str] = None
    timeframe: Optional[str] = None
    deadline_utc: Optional[str] = None
    current_price: Optional[float] = None
    reason: Optional[str] = None
    evidence: Optional[str] = None


class TweetModel(BaseModel):
    tweet_id: str
    account_name: str  # FK reference
    text: str
    created_at: datetime
    summary: Optional[SummaryModel] = None  # object instead of string
    prediction: bool = False                # query helper

    @validator("created_at", pre=True)
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v
# -----------------------
# Account in DB (Stores Tweets)
# -----------------------
class AccountModel(BaseModel):
    account_name: str = Field(..., alias="_id")
    x_user_id: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None
    profile_image_url: Optional[str] = None
    verified: Optional[bool] = None
    account_created_at: Optional[datetime] = None
    last_fetched: Optional[datetime] = None

# -----------------------
# User
# -----------------------
class AccountRefModel(BaseModel):
    username: str = Field(..., description="Twitter handle without @")
    influence: int = Field(..., ge=0, le=100, description="Influence score (0-100)")

class AgentModel(BaseModel):
    agent: str = Field(..., description="Name of the agent")
    accounts: List[AccountRefModel] = Field(default_factory=list, description="Accounts linked to the agent")
    categories: List[str] = Field(default_factory=list, description="Interest categories like ['crypto', 'stocks']")

class UserModel(BaseModel):
    walletAddress: str = Field(..., description="User's wallet address")
    agents: List[AgentModel] = Field(default_factory=list, description="List of agents with accounts")
    created_at: datetime = Field(default_factory=datetime.utcnow)

