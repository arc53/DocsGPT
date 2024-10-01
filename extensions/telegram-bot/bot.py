from typing import Final
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os
from dotenv import load_dotenv
# Load environment variables from the .env file
load_dotenv()
TOKEN : Final = os.getenv('BOT_TOKEN')
BOT_USERNAME: Final = os.getenv('BOT_USERNAME')
BASE_API_URL = 'http://localhost:7091'
#Commands

async def start_command(update : Update, context : ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello!\nThis is DocsGPT. How may I help you?")


async def about_command(update : Update, context : ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('''DocsGPT is a cutting-edge open-source solution that streamlines the process of finding information in the project documentation. With its integration of the powerful GPT models, developers can easily ask questions about a project and receive accurate answers.
Say goodbye to time-consuming manual searches, and let DocsGPT help you quickly find the information you need. Try it out and see how it revolutionizes your project documentation experience. ''')

#Handle Responses

async def handle_response(text: str, user: str)->str:
    processed: str = text.lower()
    return await fetch_answer(processed, user)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_type: str = update.message.chat.type
    text:  str = update.message.text
    print(f'User {update.message.chat.id} in {message_type} : {text}')
    if( message_type == 'group'):
        if BOT_USERNAME in text:
            new_text: str= text.replace(BOT_USERNAME, "").strip()
            response: str = await handle_response(new_text, update.message.chat.first_name)
        else:
            return
    else:
        response: str = await handle_response(text, update.message.chat.first_name)
    print('Bot : ', response)
    await update.message.reply_text(response)

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f'Update: {update} caused error {context.error}')


# Utility

async def fetch_answer(question, user):
    data = {
        'sender': user,
        'question': question,
        'history': ''
    }
    headers = {"Content-Type": "application/json",
               "Accept": "application/json"}
    response = requests.post(BASE_API_URL + '/api/answer', json=data, headers=headers)
    if response.status_code == 200:
        return response.json()['answer']
    return 'Sorry, I could not fetch the answer.'

if __name__ == '__main__':
    print("starting")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('about', about_command))

    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    app.add_error_handler(error)
    print("polling")
    app.run_polling(poll_interval = 2)
