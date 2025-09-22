from fastapi.responses import JSONResponse
from fastapi import Request, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from utils.mongo_service import  check_tweet_exists,update_user_agent, delete_user_agent, create_or_update_user_with_agent, save_combined_predictions, get_all_unique_x_influencers_ids, get_all_users, get_influencer_account_by_username, get_last_24h_predicted_tweets, get_user_agents,save_account_info , save_tweet
from utils.x_api import get_token_price, get_user_info, get_user_tweets
from utils.gpt_client import tweet_analysis, combined_predictions_analysis
from datetime import datetime
import time
import logging
from typing import Optional,Any
from config import PORT, HOST, VERSION, Allowed_Origins
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

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

class APIResponse(BaseModel):
    status: str  # "success" | "error"
    data: Optional[Any] = None
    message: str
    error: Optional[str] = None

class InfluencerSearchRequest(BaseModel):
    username: str
    walletAddress: Optional[str] = None

BATCH_SIZE = 10

async def fetch_influencers_tweets() -> list:
    """
    Fetch only the most recent tweet for each influencer.
    Returns tweets sorted newest first.
    """
    ids = await get_all_unique_x_influencers_ids()

    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i+BATCH_SIZE]

        for user_id in batch:
            if not user_id or not str(user_id).isdigit():
                logging.warning(f"Skipping invalid ID: {user_id}")
                continue

            print(f"Fetching tweets for user ID: {user_id}")
            try:
                tweets, headers = get_user_tweets(user_id, max_results=5)

                #  rate limits
                remaining = int(headers.get("x-rate-limit-remaining", 1))
                reset_time = int(headers.get("x-rate-limit-reset", time.time() + 900))

                if tweets:
                    tweets.sort(
                        key=lambda t: datetime.fromisoformat(
                            t["created_at"].replace("Z", "+00:00")
                        ),
                        reverse=True
                    )
                    most_recent = tweets[0]

                    res = await check_tweet_exists(most_recent['username'], most_recent['id'])
                    if res.get("status") == "exists":
                        logging.info(f"Tweet already exists for {most_recent['username']}")
                        continue

                    logging.info(f"New tweet found for {most_recent['username']}")
                    tweet_analysis_result = await tweet_analysis(most_recent)
                    logging.info(f"Tweet analysis result: {tweet_analysis_result}")
                    await save_tweet(most_recent['username'], most_recent, tweet_analysis_result)

                # If we are out of requests, wait until reset
                if remaining == 0:
                    sleep_for = reset_time - int(time.time())
                    logging.warning(f"Rate limit reached. Sleeping {sleep_for}s...")
                    await asyncio.sleep(sleep_for)

            except Exception as e:
                logging.error(f"Error fetching tweets for ID {user_id}: {e}")

        # After finishing one batch, wait for the next 15-min window
        if i + BATCH_SIZE < len(ids):
            logging.info("Batch finished. Sleeping 15 minutes for next window...")
            await asyncio.sleep(900)            

async def combined_prediction_analysis():
    """
    Analyze a tweet and generate a combined prediction.
    """
    logging.info("Generating combined prediction")

    try:
        tweets_data = await get_last_24h_predicted_tweets()
        logging.info(f"Fetched {len(tweets_data)} tweets for analysis")

        tweet_analysis = await combined_predictions_analysis(tweets_data)
        logging.info("Completed combined predictions analysis")
        print(tweet_analysis)

        await save_combined_predictions(tweet_analysis)

    except Exception as e:
        logging.error(f"Error in combined_prediction_analysis: {e}", exc_info=True)   
   
def success_response(data: Any = None, message: str = "OK", http_code: int = 200):
    return JSONResponse(
        status_code=http_code,
        content=APIResponse(
            status="success",
            data=data,
            message=message,
            error=None,
        ).dict()
    )

def error_response(message: str, error: str = "BadRequest", http_code: int = 400):
    return JSONResponse(
        status_code=http_code,
        content=APIResponse(
            status="error",
            data=None,
            message=message,
            error=error,
        ).dict()
    )

@app.on_event("startup")
async def startup_event():
    logging.info(f"Running on server. App version is {VERSION}")
    # await fetch_influencers_tweets()
    # await combined_prediction_analysis()
    # Add jobs
    scheduler.add_job(fetch_influencers_tweets, "interval", hours=1)
    logging.info("Scheduled: fetch_influencers_tweets every 1 hour")

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

@app.post("/user/agent/create", response_model=APIResponse)
async def create_user(request: Request):
    """
    Create or update a user and link Twitter accounts to their wallet.
    """
    try:
        body = await request.json()
        logging.info(f"Create User Request: {body}")

        wallet = body.get("walletAddress")
        accounts = body.get("accounts", [])

        if not wallet:
            return error_response("walletAddress is required", error="ValidationError", http_code=400)
        if not isinstance(accounts, list):
            return error_response("accounts must be a list", error="ValidationError", http_code=400)

        result = await create_or_update_user_with_agent(body)

        return success_response(
            data={"wallet": wallet, "user": result["user"]},
            message=f"User {result['status']} successfully"
        )

    except ValueError as error:
        # Business logic errors (e.g., agent already exists, account not found)
        logging.error(f"Validation error: {error}")
        return error_response(str(error), error="Conflict", http_code=409)

    except Exception as error:
        # Unexpected errors
        logging.exception("Unexpected error occurred")
        return error_response("Internal Server Error", error="ServerError", http_code=500)

@app.put("/user/agent/update")
async def update_user_agent_endpoint(request: Request):
    """
    Update an existing agent of a user by wallet address.
    Expected JSON body example:
    {
      "wallet": "0x123...",
      "agent_name": "AlphaAgent",
      "new_agent_name": "SuperAlpha",          # optional
      "add_accounts": [
         {"username": "elonmusk", "influence": 80},
         {"username": "nasa", "influence": 70}
      ],                                    # optional
      "remove_accounts": ["old_account"],    # optional
      "update_influences": {"nasa": 75},     # optional
      "categories": ["crypto", "stocks"]    # optional
    }
    """
    try:
        body = await request.json()
        logging.info(f"Update User Agent Request: {body}")

        wallet = body.get("wallet")
        agent_name = body.get("agent_name")

        if not wallet:
            raise HTTPException(status_code=400, detail="wallet Address is required")
        if not agent_name:
            raise HTTPException(status_code=400, detail="agentName is required")

        result = await update_user_agent(
            wallet=wallet,
            agent_name=agent_name,
            new_agent_name=body.get("new_agent_name"),
            add_accounts=body.get("add_accounts"),
            remove_accounts=body.get("remove_accounts"),
            update_influences=body.get("update_influences"),
            categories=body.get("categories"),
        )


        return success_response(
            data= result,
            message=f"User Updated successfully"
        )
    except ValueError as error:
        # Business logic errors (e.g., agent already exists, account not found)
        logging.error(f"Validation error: {error}")
        return error_response(str(error), error="Conflict", http_code=409)

    except Exception as error:
        # Unexpected errors
        logging.exception("Unexpected error occurred")
        return error_response("Internal Server Error", error="ServerError", http_code=500)

@app.delete("/user/agent")
async def delete_agent(wallet_address: str, agent_name: str):
    """
    Delete an agent from a user by wallet address using query parameters.
    Example: /user/agent/delete?wallet_address=0x123...&agent_name=MyAgent
    """
    try:
        wallet = wallet_address.strip()
        agent_name = agent_name.strip()

        if not wallet:
            raise HTTPException(status_code=400, detail="walletAddress is required")
        if not agent_name:
            raise HTTPException(status_code=400, detail="agentName is required")

        result = await delete_user_agent(wallet, agent_name)

        # return result
        return success_response(
            data= result,
            message=f"agent deleted successfully"
        )

    except ValueError as error:
        logging.error(f"Validation error: {error}")
        return error_response(str(error), error="Conflict", http_code=409)

    except Exception as error:
        logging.exception("Unexpected error occurred")
        return error_response("Internal Server Error", error="ServerError", http_code=500)

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
            "data": agents,
            "messsage": "User agents fetched successfully",
            "error": None
        }
    except ValueError as error:
        logging.error(f"Error retrieving agents for wallet {walletAddress}: {error}")
        return error_response(str(error), error="Conflict", http_code=409)

    except Exception as error:
        # Unexpected errors
        logging.exception("Unexpected error occurred")
        return error_response("Internal Server Error", error="ServerError", http_code=500)

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
            return {
            "status": "success",
            "data": influencer_doc.dict(),
            "messsage": "influencer fetched successfully",
            "error": None
            }

    except Exception as db_error:
        logging.error(f"Database lookup failed for {username}: {db_error}")
        return error_response("Database error during lookup", error="ServerError", http_code=500)

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

        return {
            "status": "success",
            "data": user_info,
            "messsage": "influencer fetched successfully",
            "error": None
        }
    except ValueError as error:
        logging.error(f"Failed to fetch from X API for {username}: {error}")
        return error_response(str(error), error="Conflict", http_code=409)
    except Exception as error:
        logging.exception("Unexpected error occurred")
        return error_response("Internal Server Error", error="ServerError", http_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
