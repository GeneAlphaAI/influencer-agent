import requests
import logging
from config import X_BEARER_TOKEN

BASE_URL = "https://api.x.com/2"

def get_user_info(username: str):
    """
    Fetch user info from X (Twitter) API by username.

    Args:
        username (str): The username to fetch.

    Returns:
        dict | None: User info JSON if successful, None otherwise.
    """
    url = f"{BASE_URL}/users/by/username/{username}"
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    params = {
        "user.fields": "id,name,username,profile_image_url,verified,created_at"
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)  # 10s timeout
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        logging.error(f"Timeout fetching user info for {username}")
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error for {username}: {e.response.status_code} {e.response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for {username}: {e}")

    return None

def get_user_tweets(user_id: str, max_results=5):
    url = f"{BASE_URL}/users/{user_id}/tweets"
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    params = {
        "max_results": max_results,
        "tweet.fields": "author_id,created_at,text",
        "expansions": "author_id",
        "exclude": "replies,retweets",
        "user.fields": "username"
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        tweets = data.get("data", [])
        users = {u["id"]: u["username"] for u in data.get("includes", {}).get("users", [])}

        for tweet in tweets:
            tweet["username"] = users.get(tweet["author_id"], None)

        return tweets

    except requests.exceptions.Timeout:
        logging.error(f"Timeout fetching tweets for {user_id}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for {user_id}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error fetching tweets for {user_id}: {e}")

    return []

def get_token_price(symbol: str) -> float:
    symbol = symbol.upper() + "USDT"  # e.g., "ETH" -> "ETHUSDT"
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    return float(data["price"])

