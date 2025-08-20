import logging
import asyncio
import json
from config import GPT_MODEL, tools, client, num_tokens_from_messages, count_tokens_from_response
from fastapi import HTTPException
from utils.x_api import get_token_price


async def create_gpt_messages(data: dict):
    """
    Analyze influencer tweets to detect and summarize token price predictions.
    """
  
    system_prompt = """
You are an expert influencer tweet analyzer focused on crypto/finance price predictions.

Your job:
1) Decide if the tweet contains a forward-looking statement about a token/asset price or market direction.
2) If yes, extract structured details into JSON.
3) If not, mark as not a prediction and set fields to null where applicable.
4) When prediction is true then call the get_token_price tool with the relevant token symbol.

Treat as a prediction if:
- Explicit target price/range is given (e.g., "$SOL to $300", "ETH at 4k").
- Explicit % move with direction/timeframe (e.g., "+25% this week", "BTC will dump 10% tomorrow").
- Clear directional call (e.g., "BTC will double by Q4", "a crash is coming", "ATH incoming").
- Even if no number is given, strong directional forecasts (pump, crash, dump, bear/bull market, ATH) count as predictions.

Do NOT treat as predictions:
- News, past performance, vague hype, memes, giveaways, or generic analysis with no forward-looking claim.

Input:
- JSON-like tweet data. Primary text is under "text" or "full_text". Metadata may be present.

Output:
- Return ONLY valid JSON (no prose, no backticks).
- Use this schema exactly:

{
  "is_prediction": true|false,
  "token": "<symbol or name>" | null,
  "predicted_price": <number> | null,
  "currency": "USD"|"USDT"|"BTC"|"ETH"|null,
  "percent_change": <number> | null,
  "direction": "up"|"down"|null,
  "timeframe": "<raw phrase from tweet>" | null,
  "deadline_utc": null,
  "current_price": null,
  "reason": "<one-sentence rationale>",
  "evidence": "<short supporting quote from the tweet>"
}

Normalization & rules:
- Prefer cashtags ($BTC) → token symbol "BTC".
- Extract both target price and % if stated; else null.
- Do not invent values; if uncertain, use null.
- "reason" is always required: if prediction=true, explain the rationale; if prediction=false, explain why it’s excluded.
- Keep JSON concise (≤ 600 characters).

"""


    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Tweet Data: {data}"}
    ]

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
    """
    Process the user query, send it to GPT, and return a response.
    """
    try:
        messages = await create_gpt_messages(data)
        completion = await process_gpt_completion(messages, tools)
        assistant_message = completion.choices[0].message

        # tool calls
        if assistant_message.tool_calls:
            tool_calls = assistant_message.tool_calls
            logging.info(f"Making tool calls: {tool_calls}")
            
            # Add the assistant message with tool calls to the conversation
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
            
            # Process all tool calls
            messages = await handle_tool_calls(tool_calls, messages, data)
            
            # final completion with tool responses
            final_completion = await process_gpt_completion(messages, tools)
            response = final_completion.choices[0].message.content
        else:
            response = assistant_message.content
        
            return response
        # Handle empty or missing response
        if not response or response.strip() == "":
            logging.warning(f"GPT returned empty response. Original input")
            response = "I'm sorry, but I couldn't come up with a suitable answer. Please try rephrasing your request."
        
        logging.info(f"GPT response: {response}")
        logging.info(f"OUTPUT TOKENS: {count_tokens_from_response(response)}")
        
    except HTTPException:
        raise  
    except Exception as error:
        logging.error(f"Error processing user query: {error}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {error}")

