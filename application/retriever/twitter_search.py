import sys
from application.retriever.base import BaseRetriever
from application.retriever.classic_rag import ClassicRAG
from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.utils import num_tokens_from_string
import requests
import base64


class TwitterRetSearch(BaseRetriever):

    def __init__(
        self,
        question,
        source,
        chat_history,
        prompt,
        chunks=2,
        token_limit=150,
        gpt_model="docsgpt",
        user_api_key=None,
    ):
        self.question = question
        self.source = source
        self.chat_history = chat_history
        self.prompt = prompt
        self.chunks = chunks
        self.gpt_model = gpt_model
        self.token_limit = (
            token_limit
            if token_limit
            < settings.MODEL_TOKEN_LIMITS.get(
                self.gpt_model, settings.DEFAULT_MAX_HISTORY
            )
            else settings.MODEL_TOKEN_LIMITS.get(
                self.gpt_model, settings.DEFAULT_MAX_HISTORY
            )
        )
        self.user_api_key = user_api_key

    def _get_data(self):
        if self.chunks == 0:
            docs = []
        else:
            # Question should ask llm to generate search query for twitter based on the question
            llm_query = f"Generate a search term for the Twitter API based on: {self.question}. Provide single or multiple words without quotes."

            messages_combine = [{"role": "user", "content": llm_query}]
            llm = LLMCreator.create_llm(
                settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=self.user_api_key
            )

            completion = llm.gen_stream(model=self.gpt_model, messages=messages_combine)
            twitter_search_query = ""
            for line in completion:
                twitter_search_query += str(line)

            results = self.search_tweets(twitter_search_query, count=int(self.chunks))
            
            # TODO work on processing the results json below by following proper schema of x api
            
            docs = []
            for i in results:
                try:
                    title = i["title"]
                    link = i["link"]
                    snippet = i["snippet"]
                    docs.append({"text": snippet, "title": title, "link": link})
                except IndexError:
                    pass
        if settings.LLM_NAME == "llama.cpp":
            docs = [docs[0]]

        return docs

    def gen(self):
        docs = self._get_data()

        # join all page_content together with a newline
        docs_together = "\n".join([doc["text"] for doc in docs])
        p_chat_combine = self.prompt.replace("{summaries}", docs_together)
        messages_combine = [{"role": "system", "content": p_chat_combine}]
        for doc in docs:
            yield {"source": doc}

        if len(self.chat_history) > 1:
            tokens_current_history = 0
            # count tokens in history
            self.chat_history.reverse()
            for i in self.chat_history:
                if "prompt" in i and "response" in i:
                    tokens_batch = num_tokens_from_string(i["prompt"]) + num_tokens_from_string(
                        i["response"]
                    )
                    if tokens_current_history + tokens_batch < self.token_limit:
                        tokens_current_history += tokens_batch
                        messages_combine.append(
                            {"role": "user", "content": i["prompt"]}
                        )
                        messages_combine.append(
                            {"role": "system", "content": i["response"]}
                        )
        messages_combine.append({"role": "user", "content": self.question})

        llm = LLMCreator.create_llm(
            settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=self.user_api_key
        )

        completion = llm.gen_stream(model=self.gpt_model, messages=messages_combine)
        for line in completion:
            yield {"answer": str(line)}

    def search(self):
        return self._get_data()

    def get_params(self):
        return {
            "question": self.question,
            "source": self.source,
            "chat_history": self.chat_history,
            "prompt": self.prompt,
            "chunks": self.chunks,
            "token_limit": self.token_limit,
            "gpt_model": self.gpt_model,
            "user_api_key": self.user_api_key
        }

    
    def get_bearer_token(self, consumer_key, consumer_secret):
        
        # Step 1: Concatenate with a colon
        bearer_token_credentials = f"{consumer_key}:{consumer_secret}"
        
        # Step 2: Base64 encode the concatenated string
        base64_encoded_credentials = base64.b64encode(bearer_token_credentials.encode('utf-8')).decode('utf-8')
        
        # Step 3: Obtain Bearer Token
        url = 'https://api.x.com/oauth2/token'
        headers = {
            'Authorization': f'Basic {base64_encoded_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
        }
        data = {
            'grant_type': 'client_credentials'
        }
        
        # Make the POST request to get the Bearer Token
        response = requests.post(url, headers=headers, data=data)
        
        # Check if the request was successful
        if response.status_code == 200:
            token_response = response.json()
            return token_response.get('access_token')
        else:
            raise Exception(f"Failed to get bearer token: {response.status_code}, {response.text}")


    # Function to search for tweets using Twitter API v1.1
    def search_tweets(self, search_term):
        oauth2_token = self.get_bearer_token(settings.TWITTER_API_KEY, settings.TWITTER_API_KEY_SECRET)
        print(oauth2_token, file=sys.stderr)
        # Parameters for the search query
        params = {
            'query': search_term,
        }
        
        # Make the GET request using httpx
        SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
        headers = {
            'Authorization': f'Bearer {oauth2_token}'
        }
        response = requests.get(SEARCH_URL, headers=headers, params=params)

        print(response.status_code, file=sys.stderr)

        # Check if the response is OK
        if response.status_code != 200:
            print(response.text, file=sys.stderr)
            raise Exception(f"Request failed: {response.status_code} {response.text}")
        
        # Parse the JSON response
        tweet_data = response.json()
        
        # Extract and return relevant tweet information
        return tweet_data.get('statuses', [])

