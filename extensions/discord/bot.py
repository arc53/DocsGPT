import os
import re

import discord
import requests
from discord.ext import commands
import dotenv

dotenv.load_dotenv()

# Replace 'YOUR_BOT_TOKEN' with your bot's token
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = '@docsgpt '
BASE_API_URL = 'http://localhost:5001'

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


def split_string(input_str):
    pattern = r'<(.*?)>'
    match = re.search(pattern, input_str)

    if match:
        content = match.group(1)
        rest = input_str[:match.start()] + input_str[match.end():]
        return content, rest.strip()
    return None, input_str


@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')


async def fetch_answer(question):
    data = {
        'sender': 'discord',
        'question': question,
        'history': ''
    }
    headers = {"Content-Type": "application/json",
               "Accept": "application/json"}
    response = requests.post(BASE_API_URL + '/api/answer', json=data, headers=headers)
    if response.status_code == 200:
        return response.json()['answer']
    return 'Sorry, I could not fetch the answer.'


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content = message.content.strip()
    prefix, content = split_string(content)
    if prefix is None:
        return

    part_prefix = "@"
    if part_prefix in prefix:
        answer = await fetch_answer(content)
        await message.channel.send(answer)

    await bot.process_commands(message)


bot.run(TOKEN)
