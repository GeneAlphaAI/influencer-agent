import logging
import asyncio
import json
from config import GPT_MODEL, tools, client
from fastapi import HTTPException
from utils.x_api import get_token_price


async def create_gpt_messages(data: dict):
    """
    Analyze influencer tweets to detect and summarize token price predictions.
    """
  
    system_prompt = """
    You are an expert influencer tweet analyzer focused on crypto/finance/stocks price predictions.

    Your job:
    1) Decide if the tweet contains a forward-looking statement about a 'token/asset' (crypto) or a 'stock' price or market direction.
    2) If yes, extract structured details into JSON using the schema below.
    3) If not, mark as not a prediction and set fields to null where applicable.
    4) Tweets may contain text, images, or both.
    5) If an image is included, analyze it as well (e.g., charts, annotations, prediction text).
    6) When prediction is true, call the get_token_price tool with the relevant token symbol.

    Treat as a prediction if:
    - Explicit target price/range is given (e.g., "$SOL to $300", "ETH at 4k", "$AAPL to 250").
    - Explicit % move with direction/timeframe (e.g., "+25% this week", "BTC will dump 10% tomorrow", "TSLA +15% in Q3").
    - Clear directional call (e.g., "BTC will double by Q4", "a crash is coming", "ATH incoming", "Dow Jones will rally").
    - Even without a number, strong directional forecasts count (pump, crash, dump, bear/bull market, ATH, breakout, rally).

    Do NOT treat as predictions:
    - News, past performance commentary, vague hype, memes, giveaways, or generic analysis without a forward-looking claim.

    Input:
    - JSON-like tweet data. Primary text is under "text" or "full_text". Metadata may be present.

    Output:
    - Return ONLY valid JSON (no prose, no backticks).
    - Use this schema exactly:

    {
    "is_prediction": true|false,
    "category": "crypto"|"stock"|null,
    "token": "<symbol>"|null,
    "name": "<asset/stock name>"|null,
    "predicted_price": <number>|null,
    "currency": "USD"|"USDT"|"BTC"|"ETH"|null,
    "direction": "up"|"down"|null,
    "timeframe": "<raw phrase from tweet>"|null,
    "deadline_utc": null,
    "current_price": null,
    "image_analysis": "<short analysis of image if present, else null>",
    "reason": "<one-sentence rationale>",
    "evidence": "<short supporting quote from the tweet>"
    }

    Normalization & rules:
    - Prefer cashtags ($BTC, $ETH, $AAPL, $TSLA) → symbol.
    - For stocks, map cashtags ($AAPL → AAPL). For crypto, map symbols ($BTC → BTC).
    - If both a target price and % move are stated, extract both; else null.
    - Do not invent values; use null if uncertain.
    - "reason" is always required: 
    • If prediction=true → explain why it qualifies.  
    • If prediction=false → explain why excluded <shortly>.  
    - Keep JSON concise (≤ 600 characters).
    """

    messages = [{"role": "system", "content": system_prompt}]

    # user content (text + optional images)
    user_content = [{"type": "text", "text": f"Tweet Data: {data}"}]

    # If tweet has images, attach them as image_url
    if "media_urls" in data:
        for url in data["media_urls"]:
            user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": url,
                        "detail": "low"
                    }
                })


    messages.append({"role": "user", "content": user_content})

    return messages


async def process_gpt_completion(messages, tools):
    """
    Asynchronously process the GPT completion with the provided messages and tools.
    """
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=GPT_MODEL,
            messages=messages,
            tools=tools
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing GPT completion: {str(e)}")


async def execute_tool_call(tool_call, data):
    """
    Execute a single tool call and return its result.
    """
    try:
        args = json.loads(tool_call.function.arguments)
        logging.debug(f"Making tool call: {args}")

        result = await _dispatch_tool_call(tool_call.function.name, args, data)

        logging.info(f"Tool call result: {result}")
        return {
            "tool_call_id": tool_call.id,
            "function_name": tool_call.function.name,
            "content": str(result) if result else "No data found."
        }
    except Exception as err:
        logging.error(f"Error during tool call execution: {err}")
        if isinstance(err, HTTPException):
            raise err
        return {
            "tool_call_id": tool_call.id,
            "function_name": tool_call.function.name,
            "content": f"Error executing function: {str(err)}"
         }


async def _dispatch_tool_call(function_name, args, data):
    """Dispatch tool call to appropriate handler based on function name."""

    # Map other function names to their handlers
    tool_handlers = {
        "get_token_price": lambda: get_token_price(args["symbol"]),
    }

    handler = tool_handlers.get(function_name)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unknown function call: {function_name}")

    return handler()


async def handle_tool_calls(tool_calls, messages, data):
    """
    Handle multiple tool calls in parallel and update messages with responses.
    """
    try:
        # Execute all tool calls in parallel
        tool_results = await asyncio.gather(
            *[execute_tool_call(tool_call, data) for tool_call in tool_calls]
        )

        # Add tool responses to messages
        for result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "name": result["function_name"],
                "content": result["content"]
            })
        return messages

    except Exception as err:
        logging.error(f"Error during tool calls handling: {err}")
        raise HTTPException(status_code=500, detail=f"Error processing function calls: {err}")


async def tweet_analysis(data):
    try:
        messages = await create_gpt_messages(data)
        completion = await process_gpt_completion(messages, tools)
        assistant_message = completion.choices[0].message

        # handle tool calls
        if assistant_message.tool_calls:
            tool_calls = assistant_message.tool_calls
            logging.info(f"Making tool calls: {tool_calls}")

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    } for tool_call in tool_calls
                ]
            })

            messages = await handle_tool_calls(tool_calls, messages, data)
            final_completion = await process_gpt_completion(messages, tools)
            response = final_completion.choices[0].message.content
        else:
            response = assistant_message.content

        if not response or response.strip() == "":
            response = '{"is_prediction": false, "reason": "empty GPT response"}'

        try:
            return json.loads(response)
        except Exception as parse_err:
            logging.error(f"Failed to parse GPT response: {response}, error: {parse_err}")
            return {"raw_response": response, "parse_error": str(parse_err)}

    except Exception as error:
        logging.error(f"Error processing user query: {error}", exc_info=True)
        return {"error": str(error), "status": "failed"}
