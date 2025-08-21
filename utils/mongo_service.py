import json
import logging
from utils.db import db
from utils.db import db
from datetime import datetime, timedelta
from typing import List, Optional
from utils.models import SummaryModel, UserModel, AccountModel, TweetModel, AccountRefModel,AgentModel
from fastapi import HTTPException

# -----------------------
# USER FUNCTIONS
# -----------------------
async def create_or_update_user_with_agent(data: dict):
    wallet = data["walletAddress"]
    agent_name = data["agentName"]
    accounts = data.get("accounts", [])
    categories = data.get("categories", [])

    # ✅ Only keep username + influence
    account_refs = []
    for acc in accounts:
        username = acc["username"].strip().lower()
        influence = acc["influence"]

        # (Optional) Ensure account exists in accounts collection
        db_account = await db.accounts.find_one({"username": username})
        if not db_account:
            raise ValueError(f"Account with username '{username}' not found in accounts collection")

        account_refs.append({"username": username, "influence": influence})

    existing_user = await db.users.find_one({"walletAddress": wallet})

    if not existing_user:
        # 🚀 New user with agent
        new_user = UserModel(
            walletAddress=wallet,
            agents=[AgentModel(agent=agent_name, accounts=account_refs, categories=categories)]
        ).dict()
        await db.users.insert_one(new_user)
        return {"status": "created", "user": new_user}

    # 🚨 Ensure agents list exists
    if "agents" not in existing_user or not isinstance(existing_user["agents"], list):
        existing_user["agents"] = []

    # 🔍 Look for existing agent
    agent_found = False
    for agent in existing_user["agents"]:
        if agent["agent"] == agent_name:
            agent_found = True

            # Merge accounts by username
            existing_usernames = {a["username"] for a in agent.get("accounts", [])}
            for acc in account_refs:
                if acc["username"] not in existing_usernames:
                    agent.setdefault("accounts", []).append(acc)

            # Merge categories
            existing_categories = set(agent.get("categories", []))
            existing_categories.update(categories)
            agent["categories"] = list(existing_categories)
            break

    # ➕ If agent not found, create one
    if not agent_found:
        existing_user["agents"].append(
            AgentModel(agent=agent_name, accounts=account_refs, categories=categories).dict()
        )

    await db.users.replace_one({"walletAddress": wallet}, existing_user)
    return {"status": "updated", "user": existing_user}

async def get_user_agents(wallet: str) -> list:
    pipeline = [
        {"$match": {"walletAddress": wallet}},
        {"$unwind": "$agents"},
        {"$unwind": "$agents.accounts"},

        {
            "$lookup": {
                "from": "accounts",
                "localField": "agents.accounts.username",
                "foreignField": "username",
                "as": "agents.accounts.account_info"
            }
        },
        {"$unwind": {"path": "$agents.accounts.account_info", "preserveNullAndEmptyArrays": True}},

        {
            "$lookup": {
                "from": "tweets",
                "let": {"uname": "$agents.accounts.username"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$eq": [
                                    {"$toLower": "$account_name"},
                                    {"$toLower": "$$uname"}
                                ]
                            }
                        }
                    },
                    {"$project": {"_id": 0}}   # ✅ strip ObjectId
                ],
                "as": "agents.accounts.tweets"
            }
        },

        {
            "$group": {
                "_id": {
                    "agent": "$agents.agent",
                    "categories": "$agents.categories",
                    "predictions": "$agents.predictions"
                },
                "accounts": {"$push": "$agents.accounts"}
            }
        },

        {
            "$project": {
                "_id": 0,
                "agent": "$_id.agent",
                "categories": "$_id.categories",
                "predictions": "$_id.predictions",
                "accounts": 1
            }
        }
    ]

    cursor = db.users.aggregate(pipeline)
    return await cursor.to_list(length=None)

async def get_all_unique_accounts_from_all_users() -> list:
    """
    Retrieve all unique accounts (by username) across all agents for all users.
    """
    cursor = db.users.find({}, {"_id": 0, "agents.accounts": 1})
    unique_accounts = {}

    async for user in cursor:
        for agent in user.get("agents", []):
            for account in agent.get("accounts", []):
                username = account["username"]
                if username not in unique_accounts:
                    unique_accounts[username] = account

    return list(unique_accounts.values())

# -----------------------
# ACCOUNT FUNCTIONS
# -----------------------

async def save_tweet(account_name: str, tweet_data: dict, summary_data: Optional[dict] = None) -> dict:
    try:
        tweets_collection = db.tweets
        tweet_id = str(tweet_data.get("id") or tweet_data.get("tweet_id"))
        
        if not tweet_id:
            raise HTTPException(status_code=400, detail="Tweet must contain 'id' or 'tweet_id'")
        
        account_key = account_name.lower()
        existing = await tweets_collection.find_one({
            "account_name": account_key,
            "tweet_id": tweet_id
        })
        
        if existing:
            return {"id": str(existing["_id"]), "status": "exists"}
        
        # Extract attachments as list of strings
        raw_attachments = tweet_data.get("media_urls", [])
        attachments = []
        
        if isinstance(raw_attachments, dict):
            # Use media_keys if dict
            attachments = raw_attachments.get("media_urls", [])
        elif isinstance(raw_attachments, list):
            attachments = raw_attachments
        else:
            attachments = []
        
        # Parse summary if present
        summary_obj = None
        if summary_data:
            if isinstance(summary_data, str):
                summary_data = json.loads(summary_data)
            summary_obj = SummaryModel(**summary_data)
        
        # Handle created_at field conversion
        created_at = tweet_data.get("created_at")
        if isinstance(created_at, str):
            # Handle various datetime string formats
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                # Try other common formats if ISO format fails
                try:
                    created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Fallback to current time if parsing fails
                    created_at = datetime.utcnow()
        elif created_at is None:
            created_at = datetime.utcnow()
        
        tweet = TweetModel(
            tweet_id=tweet_id,
            account_name=account_key,
            text=tweet_data.get("text") or tweet_data.get("full_text", ""),
            attachments=attachments,
            created_at=created_at,
            summary=summary_obj,
            prediction=summary_obj.is_prediction if summary_obj else False
        )
        
        # Convert to dict and handle datetime serialization for MongoDB
        tweet_dict = tweet.dict()
        # Ensure datetime is properly converted for MongoDB
        if isinstance(tweet_dict.get("created_at"), datetime):
            tweet_dict["created_at"] = tweet_dict["created_at"]
        
        result = await tweets_collection.insert_one(tweet_dict)
        logging.info(f"Saved tweet for {account_name}: {tweet_id} with ID {result.inserted_id}")
        return {"id": str(result.inserted_id), "status": "created"}
        
    except Exception as e:
        logging.error(f"Error saving tweet for {account_name}: {str(e)}")
        return {"error": str(e), "status": "failed"}


async def check_tweet_exists(account_name: str, tweet_id: str) -> dict:
    """
    Check if a tweet already exists in the database for a given account.
    Returns dict with status and id if found.
    """
    try:
        tweet_id = str(tweet_id)  # normalize
        account_key = account_name.lower()  # normalize

        print(f"Checking tweet for {account_key}: {tweet_id}...")

        tweets_collection = db.tweets
        existing = await tweets_collection.find_one({
            "account_name": account_key,
            "tweet_id": tweet_id
        })
        # print(f"Existing tweet check for {account_key}: {tweet_id} - {existing is not None}")

        if existing:
            return {"id": str(existing["_id"]), "status": "exists"}
        return {"id": None, "status": "not_found"}

    except Exception as e:
        print(f"Error checking tweet for {account_name}: {str(e)}")
        return {"error": str(e), "status": "failed"}
    
async def save_account_info(account_data: dict):
    """
    Save or update account metadata in the accounts collection.
    Expects account_data like:
    {
        'name': 'Elon Musk',
        'id': '44196397',
        'created_at': '2009-06-02T20:12:29.000Z',
        'username': 'elonmusk',
        'profile_image_url': 'https://...',
        'verified': False
    }
    """
    # Convert created_at string to datetime if present
    created_at_dt = None
    if account_data.get("created_at"):
        try:
            created_at_dt = datetime.fromisoformat(account_data["created_at"].replace("Z", "+00:00"))
        except ValueError:
            pass  # ignore if parsing fails

    update_data = {
        "account_name": account_data.get("username", "").strip().lower(),  # <-- required field
        "name": account_data.get("name"),
        "x_user_id": account_data.get("id"),
        "username": account_data.get("username", "").strip().lower(),
        "profile_image_url": account_data.get("profile_image_url"),
        "verified": account_data.get("verified"),
    }


    if created_at_dt:
        update_data["account_created_at"] = created_at_dt

    await db.accounts.update_one(
        {"_id": account_data["username"]},
        {"$set": update_data},
        upsert=True
    )

async def get_all_unique_x_influencers_ids() -> List[str]:
    """
    Retrieve all unique X user IDs from the accounts collection.
    Only returns non-null values.
    """
    user_ids = await db.accounts.distinct("x_user_id")
    return [uid for uid in user_ids if uid]  # filter out None or empty strings

async def get_influencer_account_by_username(username: str) -> Optional[AccountModel]:
    """Retrieve influencer account by username (case-insensitive)"""
    username = username.strip().lower()  # Normalize input
    
    # Case-insensitive search using $regex
    doc = await db.accounts.find_one(
        {"_id": {"$regex": f"^{username}$", "$options": "i"}},
        {
            "_id": 1,
            "x_user_id": 1,
            "name": 1,
            "username": 1,
            "profile_image_url": 1,
            "verified": 1,
            "account_created_at": 1,
            "tweets": 1,
            "last_fetched": 1
        }
    )
    return AccountModel(**doc) if doc else None
