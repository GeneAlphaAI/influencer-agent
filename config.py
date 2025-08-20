import os
import logging
from openai import OpenAI
from dotenv import load_dotenv
import sys

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


GPT_MODEL = "gpt-4o-mini"
PORT = os.getenv("PORT", "127.0.0.1")
HOST = os.getenv("HOST", 8000)
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "fkjgldfjgldjfglj")

SHORT_TERM_MEMORY_LIMIT = 20

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

with open("version", "r") as version_file:
    VERSION = version_file.read().strip()

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_token_price",
            "description": "Fetch the current price of a cryptocurrency token by its symbol (e.g., BTC, ETH, SOL).",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The ticker symbol of the token (e.g., BTC, ETH, SOL)."
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]

