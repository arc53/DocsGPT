import os
import hashlib
import httpx
import re
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from dotenv import load_dotenv

load_dotenv()
API_BASE = os.getenv("API_BASE", "https://gptcloud.arc53.com")
API_URL =  API_BASE + "/api/answer"

# Slack bot token and signing secret
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

# OpenAI API key for DocsGPT (replace this with your actual API key)
DOCSGPT_API_KEY = os.getenv("DOCSGPT_API_KEY")

# Initialize Slack app
app = AsyncApp(token=SLACK_BOT_TOKEN)

def encode_conversation_id(conversation_id: str) -> str:
    """
        Encodes 11 length Slack conversation_id to 12 length string
        Args:
        conversation_id (str): The 11 digit slack conversation_id.
        Returns:
            str: Hashed id.
    """    
    # Create a SHA-256 hash of the string
    hashed_id = hashlib.sha256(conversation_id.encode()).hexdigest()

    # Take the first 24 characters of the hash
    hashed_24_char_id = hashed_id[:24]
    return hashed_24_char_id

async def generate_answer(question: str, messages: list, conversation_id: str | None) -> dict:
    """Generates an answer using the external API."""
    payload = {
        "question": question,
        "api_key": DOCSGPT_API_KEY,
        "history": messages,
        "conversation_id": conversation_id,
    }
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    timeout = 60.0
    async with httpx.AsyncClient() as client:
        response = await client.post(API_URL, json=payload, headers=headers, timeout=timeout)

        if response.status_code == 200:
            data = response.json()
            conversation_id = data.get("conversation_id")
            answer = data.get("answer", "Sorry, I couldn't find an answer.")
            return {"answer": answer, "conversation_id": conversation_id}
        else:
            print(response.json())
            return {"answer": "Sorry, I couldn't find an answer.", "conversation_id": None}

@app.message(".*")
async def message_docs(message, say):
    client = app.client
    channel = message['channel']
    thread_ts = message['thread_ts']
    user_query = message['text']    
    await client.assistant_threads_setStatus(
        channel_id = channel,
        thread_ts = thread_ts,
        status = "is generating your answer...",
    )

    docs_gpt_channel_id = encode_conversation_id(thread_ts)
    
    # Get response from DocsGPT
    response = await generate_answer(user_query,[], docs_gpt_channel_id)
    answer = convert_to_slack_markdown(response['answer'])

    # Respond in Slack
    await client.chat_postMessage(text = answer, mrkdwn= True, channel= message['channel'],
        thread_ts = message['thread_ts'],)

def convert_to_slack_markdown(markdown_text: str):
    # Convert bold **text** to *text* for Slack
    slack_text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', markdown_text)  # **text** to *text*

    # Convert italics _text_ to _text_ for Slack
    slack_text = re.sub(r'_(.*?)_', r'_\1_', slack_text)  # _text_ to _text_

    # Convert inline code `code` to `code` (Slack supports backticks for inline code)
    slack_text = re.sub(r'`(.*?)`', r'`\1`', slack_text)

    # Convert bullet points with single or no spaces to filled bullets (•)
    slack_text = re.sub(r'^\s{0,1}[-*]\s+', ' • ', slack_text, flags=re.MULTILINE)

    # Convert bullet points with multiple spaces to hollow bullets (◦)
    slack_text = re.sub(r'^\s{2,}[-*]\s+', '\t◦ ', slack_text, flags=re.MULTILINE)

    # Convert headers (##) to bold in Slack
    slack_text = re.sub(r'^\s*#{1,6}\s*(.*?)$', r'*\1*', slack_text, flags=re.MULTILINE)

    return slack_text

async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()

# Start the app
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())