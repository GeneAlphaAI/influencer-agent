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
    image_analysis: Optional[str] = None
    reason: Optional[str] = None
    evidence: Optional[str] = None


class TweetModel(BaseModel):
    tweet_id: str
    account_name: str
    text: str
    attachments: List[str] = Field(default_factory=list)
    created_at: datetime
    summary: Optional[SummaryModel] = None
    prediction: bool = False

    @validator("created_at", pre=True)
    def parse_datetime(cls, v):
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                try:
                    return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        return datetime.strptime(v, "%a %b %d %H:%M:%S +0000 %Y")  # Twitter format
                    except ValueError:
                        return datetime.utcnow() 
        elif v is None:
            return datetime.utcnow()  
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
    influence: float = Field(..., ge=0, le=100, description="Influence score (0-100)")

class AgentModel(BaseModel):
    agent: str = Field(..., description="Name of the agent")
    accounts: List[AccountRefModel] = Field(default_factory=list, description="Accounts linked to the agent")
    categories: List[str] = Field(default_factory=list, description="Interest categories like ['crypto', 'stocks']")
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UserModel(BaseModel):
    walletAddress: str = Field(..., description="User's wallet address")
    agents: List[AgentModel] = Field(default_factory=list, description="List of agents with accounts")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CombinedPredictionModel(BaseModel):
    agent_id: str = Field(..., description="Unique identifier of the agent")
    user_wallet: str = Field(..., description="Wallet address of the agent’s user")
    token: str = Field(..., description="Token/Stock being predicted")
    predicted_price: Optional[float] = None
    currency: Optional[str] = None
    direction: Optional[str] = None
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0–1)")
    reasoning: Optional[str] = None
    supporting_influencers: List[AccountRefModel] = Field(
        default_factory=list,
        description="List of influencers retained after filtering"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator("updated_at", pre=True, always=True)
    def set_updated(cls, v):
        return v or datetime.utcnow()
