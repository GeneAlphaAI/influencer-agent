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
        "tweet.fields": "author_id,created_at,text,attachments",
        "expansions": "author_id,attachments.media_keys",
        "exclude": "replies,retweets",
        "user.fields": "username",
        "media.fields": "url,preview_image_url,type"
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        tweets = data.get("data", [])
        users = {u["id"]: u["username"] for u in data.get("includes", {}).get("users", [])}
        media_map = {m["media_key"]: m for m in data.get("includes", {}).get("media", [])}

        for tweet in tweets:
            tweet["username"] = users.get(tweet["author_id"], None)

            # If tweet has media, attach resolved URLs
            if "attachments" in tweet and "media_keys" in tweet["attachments"]:
                media_urls = []
                for key in tweet["attachments"]["media_keys"]:
                    media_item = media_map.get(key)
                    if media_item:
                        if media_item["type"] == "photo":
                            media_urls.append(media_item.get("url"))
                        elif media_item["type"] in ["video", "animated_gif"]:
                            media_urls.append(media_item.get("preview_image_url"))
                if media_urls:
                    tweet["media_urls"] = media_urls

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

