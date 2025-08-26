from unittest import result
from fastapi.responses import FileResponse
from fastapi import Request, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from utils.mongo_service import  check_tweet_exists, create_or_update_user_with_agent, save_combined_predictions, get_all_unique_x_influencers_ids, get_all_users, get_influencer_account_by_username, get_last_24h_predicted_tweets, get_user_agents,save_account_info , save_tweet
from utils.x_api import get_token_price, get_user_info, get_user_tweets
from utils.gpt_client import tweet_analysis, combined_predictions_analysis
from datetime import datetime
import logging
from typing import Optional
from config import PORT, HOST, VERSION, Allowed_Origins
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

app = FastAPI(
    title="Influencer Agent",
    description="Influencer Agent API",
    version=VERSION
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=Allowed_Origins, 
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

class QueryRequest(BaseModel):
    query: str
    userId: str
    groupId: str
    username: str
    groupname: str

class InfluencerSearchRequest(BaseModel):
    username: str
    walletAddress: Optional[str] = None


async def fetch_influencers_tweets() -> list:
    """
    Fetch only the most recent tweet for each influencer.
    Returns tweets sorted newest first.
    """
    ids = await get_all_unique_x_influencers_ids()

    # latest_tweets = []

    for user_id in ids:
        if not user_id or not str(user_id).isdigit():
            logging.warning(f"Skipping invalid ID: {user_id}")
            continue

        try:
            tweets = get_user_tweets(user_id, max_results=5)  # Twitter API min=5
          
            if tweets:
                # Pick the most recent tweet for this account
                tweets.sort(
                    key=lambda t: datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
                    reverse=True
                )
                most_recent = tweets[0]
         
                # latest_tweets.append(most_recent)
                res = await check_tweet_exists(most_recent['username'], most_recent['id'])

                if res.get("status") == "exists":
                    logging.info(f"Tweet already exists for {most_recent['username']}")
                    return
                else:
                    logging.info(f"New tweet found for {most_recent['username']}")
                    tweet_analysis_result = await tweet_analysis(most_recent)  # Analyze the tweet
                    logging.info(f"Tweet analysis result: {tweet_analysis_result}")
                    await save_tweet(most_recent['username'],most_recent,tweet_analysis_result)
        except Exception as e:
            logging.error(f"Error fetching tweets for ID {user_id}: {e}")

    # Sort across all accounts newest first
    # latest_tweets.sort(
    #     key=lambda t: datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
    #     reverse=True
    # )
    # return latest_tweets

async def combined_prediction_analysis():
    """
    Analyze a tweet and generate a combined prediction.
    """
    logging.info("Generating combined prediction")

    try:
        tweets_data = await get_last_24h_predicted_tweets()
        logging.debug(f"Fetched {len(tweets_data)} tweets for analysis")

        tweet_analysis = await combined_predictions_analysis(tweets_data)
        logging.debug("Completed combined predictions analysis")

        await save_combined_predictions(tweet_analysis)
        logging.info("Successfully saved combined predictions")

    except Exception as e:
        logging.error(f"Error in combined_prediction_analysis: {e}", exc_info=True)
       
   

@app.on_event("startup")
async def startup_event():
    logging.info(f"Running on server. App version is {VERSION}")

    # Add jobs
    scheduler.add_job(fetch_influencers_tweets, "interval", hours=4)
    logging.info("Scheduled: fetch_influencers_tweets every 4 hours")

    scheduler.add_job(combined_prediction_analysis, "interval", hours=12)
    logging.info("Scheduled: combined_prediction_analysis every 12 hours")

    # Start scheduler 
    if not scheduler.running:
        scheduler.start()
        logging.info("Scheduler started")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    logging.info("Scheduler stopped")


@app.post("/user/agent/create")
async def create_user(request: Request):
    """
    Create or update a user and link Twitter accounts to their wallet.
    Expected JSON body:
    {
      "walletAddress": "0x123...",
      "agentName": "MyAgent",
      "accounts": [
         {"username": "elonmusk", "name": "Elon Musk", "influence": 80},
         {"username": "nasa", "name": "NASA", "influence": 70}
      ],
      "categories": ["crypto", "stocks"]
    }
    """
    try:
        body = await request.json()
        logging.info(f"Create User Request: {body}")

        wallet = body.get("walletAddress")
        accounts = body.get("accounts", [])

        if not wallet:
            raise HTTPException(status_code=400, detail="walletAddress is required")
        if not isinstance(accounts, list):
            raise HTTPException(status_code=400, detail="accounts must be a list")

        await create_or_update_user_with_agent(body)
        # result = get_user_info("elonmusk")
        # print(result)
        return {
            "status": "success",
            "wallet": wallet,
            "linked_accounts": accounts
        }

    except ValueError as error:
        logging.error(f"Invalid JSON: {error}")
        raise HTTPException(status_code=400, detail="Invalid Input")

    except HTTPException:
        logging.error(f"HTTP Exception: {error}")
        raise  # Let FastAPI handle HTTPExceptions

    except Exception as error:
        logging.error(f"Unexpected error: {error}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/user/agent/get")
async def get_agents(walletAddress: str):
    """
    Retrieve all agents for a given user by wallet address.
    
    Query Param:
        walletAddress: str (required)
    
    Example:
        GET /agent/get?walletAddress=0x123...
    """
    try:
        if not walletAddress:
            raise HTTPException(status_code=400, detail="walletAddress is required")

        agents = await get_user_agents(walletAddress)

        return {
            "status": "success",
            "wallet": walletAddress,
            "agents": agents
        }

    except HTTPException:
        raise
    except Exception as error:
        logging.error(f"Error retrieving agents for wallet {walletAddress}: {error}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/influencer/search")
async def search_influencer(payload: InfluencerSearchRequest):
    """
    Search for an influencer by username.
    - First check MongoDB `accounts` collection.
    - If not found, fetch from X API and save.
    - Optionally link influencer to a wallet if `walletAddress` is provided.
    """
    username = payload.username.strip().lower()
    wallet = payload.walletAddress

    logging.info(f"Searching influencer: username={username}, wallet={wallet}")

    # 1. Check if influencer exists in DB
    try:
        influencer_doc = await get_influencer_account_by_username(username)
        print(f"Influencer found in DB: {influencer_doc}")
        if influencer_doc:
            logging.info(f"Influencer found in DB: {username}")
            return {"status": "success", "source": "database", "data": influencer_doc.dict()}

    except Exception as db_error:
        logging.error(f"Database lookup failed for {username}: {db_error}")
        raise HTTPException(status_code=500, detail="Database error during lookup")

    # 2. If not in DB, fetch from X API
    try:
        logging.info(f"Fetching influencer from X API: {username}")
        influencer_data = get_user_info(username)  # sync function returns dict
        print(influencer_data)

        # Extract user info
        user_info = influencer_data.get("data")
        if not user_info:
            raise ValueError("No 'data' key in X API response")

        # Save to MongoDB
        await save_account_info(user_info)

        return {"status": "success", "source": "x_api", "data": user_info}

    except Exception as api_error:
        logging.error(f"Failed to fetch from X API for {username}: {api_error}")
        raise HTTPException(status_code=502, detail="Failed to fetch influencer from X API")



if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
