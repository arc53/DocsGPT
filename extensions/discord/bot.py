import os
import re
import logging
import aiohttp
import discord
from discord.ext import commands
import dotenv

dotenv.load_dotenv()

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = '!'  # Command prefix
BASE_API_URL = os.getenv("API_BASE", "https://gptcloud.arc53.com")
API_URL = BASE_API_URL + "/api/answer"
API_KEY = os.getenv("API_KEY")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Store conversation history per user
conversation_histories = {}

def chunk_string(text, max_length=2000):
    """Splits a string into chunks of a specified maximum length."""
    # Create list to store the split strings
    chunks = []
    # Loop through the text, create substrings with max_length
    while len(text) > max_length:
        # Find last space within the limit
        idx = text.rfind(' ', 0, max_length)
        # Ensure we don't have an empty part
        if idx == -1:
            # If no spaces, just take chunk
            chunks.append(text[:max_length])
            text = text[max_length:]
        else:
            # Push whatever we've got up to the last space
            chunks.append(text[:idx])
            text = text[idx+1:]
    # Catches the remaining part
    chunks.append(text)
    return chunks

def escape_markdown(text):
    """Escapes Discord markdown characters."""
    escape_chars = r'\*_$$$$()~>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def split_string(input_str):
    """Splits the input string to detect bot mentions."""
    pattern = r'^<@!?{0}>\s*'.format(bot.user.id)
    match = re.match(pattern, input_str)
    if match:
        content = input_str[match.end():].strip()
        return str(bot.user.id), content
    return None, input_str

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

async def generate_answer(question, messages, conversation_id):
    """Generates an answer using the external API."""
    payload = {
        "question": question,
        "api_key": API_KEY,
        "history": messages,
        "conversation_id": conversation_id
    }
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                conversation_id = data.get("conversation_id")
                answer = data.get("answer", "Sorry, I couldn't find an answer.")
                return {"answer": answer, "conversation_id": conversation_id}
            else:
                return {"answer": "Sorry, I couldn't find an answer.", "conversation_id": None}

@bot.command(name="start")
async def start(ctx):
    """Handles the /start command."""
    await ctx.send(f"Hi {ctx.author.mention}! How can I assist you today?")

@bot.command(name="custom_help")
async def custom_help_command(ctx):
    """Handles the /custom_help command."""
    help_text = (
        "Here are the available commands:\n"
        "`!start` - Begin a new conversation with the bot\n"
        "`!help` - Display this help message\n\n"
        "You can also mention me or send a direct message to ask a question!"
    )
    await ctx.send(help_text)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Process commands first
    await bot.process_commands(message)

    # Check if the message is in a DM channel
    if isinstance(message.channel, discord.DMChannel):
        content = message.content.strip()
    else:
        # In guild channels, check if the message mentions the bot at the start
        content = message.content.strip()
        prefix, content = split_string(content)
        if prefix is None:
            return
        part_prefix = str(bot.user.id)
        if part_prefix != prefix:
            return  # Bot not mentioned at the start, so do not process

    # Now process the message
    user_id = message.author.id
    if user_id not in conversation_histories:
        conversation_histories[user_id] = {
            "history": [],
            "conversation_id": None
        }

    conversation = conversation_histories[user_id]
    conversation["history"].append({"prompt": content})

    # Generate the answer
    response_doc = await generate_answer(
        content,
        conversation["history"],
        conversation["conversation_id"]
    )
    answer = response_doc["answer"]
    conversation_id = response_doc["conversation_id"]

    answer_chunks = chunk_string(answer)
    for chunk in answer_chunks:
        await message.channel.send(chunk)

    conversation["history"][-1]["response"] = answer
    conversation["conversation_id"] = conversation_id

    # Keep conversation history to last 10 exchanges
    conversation["history"] = conversation["history"][-10:]

bot.run(TOKEN)