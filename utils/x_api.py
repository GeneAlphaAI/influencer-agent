import requests
import logging
from typing import Optional
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

        return tweets, r.headers

    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for {user_id}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error fetching tweets for {user_id}: {e}")

    return [], {}


def get_token_price_binance(symbol: str) -> Optional[float]:
    """
    Improved Binance API version with better error handling
    """
    symbol = symbol.upper() + "USDT"
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise exception for bad status codes
        
        data = response.json()
        
        if "price" in data:
            return float(data["price"])
        else:
            # Try alternative symbol format (without USDT)
            alt_symbol = symbol.replace("USDT", "")
            logging.warning(f"Price not found for {symbol}, trying alternative symbols...")
            
            # Try with different trading pairs
            for pair in ["BUSD", "USDC", "BTC"]:
                alt_url = f"https://api.binance.com/api/v3/ticker/price?symbol={alt_symbol}{pair}"
                alt_response = requests.get(alt_url, timeout=5)
                alt_data = alt_response.json()
                
                if "price" in alt_data:
                    # If we get price in other pair, we might need to convert
                    if pair != "USDT":
                        # Get conversion rate (simplified approach)
                        usdt_pair = f"{pair}USDT"
                        conv_url = f"https://api.binance.com/api/v3/ticker/price?symbol={usdt_pair}"
                        conv_response = requests.get(conv_url, timeout=5)
                        conv_data = conv_response.json()
                        
                        if "price" in conv_data:
                            return float(alt_data["price"]) * float(conv_data["price"])
                    else:
                        return float(alt_data["price"])
            
            logging.warning(f"Price not found for any trading pair of {symbol}")
            return None
            
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None
    except ValueError as e:
        logging.error(f"JSON parsing failed: {e}")
        return None

def get_token_price_gecko(symbol: str) -> Optional[float]:
    """
    Get token price using CoinGecko API
    """
    symbol = symbol.lower()
    
    # First, get the coin ID from symbol
    url = "https://api.coingecko.com/api/v3/coins/list"
    try:
        response = requests.get(url, timeout=10)
        coins = response.json()
        
        # Find coin by symbol
        coin_id = None
        for coin in coins:
            if coin['symbol'].lower() == symbol:
                coin_id = coin['id']
                break
        
        if not coin_id:
            logging.warning(f"Coin not found for symbol: {symbol}")
            return None
        
        # Get price data
        price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        price_response = requests.get(price_url, timeout=10)
        price_data = price_response.json()
        
        if coin_id in price_data and 'usd' in price_data[coin_id]:
            return price_data[coin_id]['usd']
        else:
            logging.warning(f"Price not found for {symbol}: {price_data}")
            return None
            
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return None

def get_token_price_cryptocompare(symbol: str) -> Optional[float]:
    """
    Get token price using CryptoCompare API
    """
    symbol = symbol.upper()
    url = f"https://min-api.cryptocompare.com/data/price?fsym={symbol}&tsyms=USD"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if 'USD' in data:
            return data['USD']
        else:
            logging.warning(f"Price not found for {symbol}: {data}")
            return None
            
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None
    
def get_token_price(symbol: str) -> Optional[float]:
    """
    Universal function that tries multiple APIs with fallback
    """

    # Try CryptoCompare
    price = get_token_price_cryptocompare(symbol)
    if price is not None:
        return price
    
    # Try Binance 
    logging.info(f"Trying Binance for {symbol}")
    price = get_token_price_binance(symbol)
    if price is not None:
        return price

    # Try CoinGecko
    logging.info(f"Trying CoinGecko for {symbol}")
    price = get_token_price_gecko(symbol)
    if price is not None:
        return price
    
    logging.error(f"Could not get price for {symbol} from any API")
    return None