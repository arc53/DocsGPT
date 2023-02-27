import requests
import dotenv
import os
import json

dotenv.load_dotenv()
docsgpt_url = os.getenv("docsgpt_url")
chatwoot_url = os.getenv("chatwoot_url")
docsgpt_key = os.getenv("docsgpt_key")
chatwoot_token = os.getenv("chatwoot_token")


def send_to_bot(sender, message):
    data = {
        'sender': sender,
        'question': message,
        'api_key': docsgpt_key,
        'embeddings_key': docsgpt_key,
        'history': ''
    }
    headers = {"Content-Type": "application/json",
               "Accept": "application/json"}

    r = requests.post(f'{docsgpt_url}/api/answer',
                      json=data, headers=headers)
    return r.json()['answer']


def send_to_chatwoot(account, conversation, message):
    data = {
        'content': message
    }
    url = f"{chatwoot_url}/api/v1/accounts/{account}/conversations/{conversation}/messages"
    headers = {"Content-Type": "application/json",
               "Accept": "application/json",
               "api_access_token": f"{chatwoot_token}"}

    r = requests.post(url,
                      json=data, headers=headers)
    return r.json()


from flask import Flask, request
app = Flask(__name__)


@app.route('/docsgpt', methods=['POST'])
def docsgpt():
    data = request.get_json()
    message_type = data['message_type']
    message = data['content']
    conversation = data['conversation']['id']
    contact = data['sender']['id']
    account = data['account']['id']

    if(message_type == "incoming"):
        bot_response = send_to_bot(contact, message)
        create_message = send_to_chatwoot(
            account, conversation, bot_response)
        response = requests.post(
            url="https://86x89umx77.execute-api.eu-west-2.amazonaws.com/docsgpt-logs",
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            data=json.dumps({
                "answer": str(bot_response),
                "question": str(message),
                "source": "chatwoot"
            })
        )
    else:
        return "Not an incoming message"

    return create_message

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')