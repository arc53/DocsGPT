Fortunately, there are many providers for LLMs, and some of them can even be run locally.

There are two models used in the app:
1. Embeddings.
2. Text generation.

By default, we use OpenAI's models, but if you want to change it or even run it locally, it's very simple!

### Go to .env file or set environment variables:

`LLM_NAME=<your Text generation>`

`API_KEY=<api_key for Text generation>`

`EMBEDDINGS_NAME=<llm for embeddings>`

`EMBEDDINGS_KEY=<api_key for embeddings>`

`VITE_API_STREAMING=<true or false (true if using openai, false for all others)>`

You don't need to provide keys if you are happy with users providing theirs, so make sure you set `LLM_NAME` and `EMBEDDINGS_NAME`.

Options:  
LLM_NAME (openai, manifest, cohere, Arc53/docsgpt-14b, Arc53/docsgpt-7b-falcon, llama.cpp)  
EMBEDDINGS_NAME (openai_text-embedding-ada-002, huggingface_sentence-transformers/all-mpnet-base-v2, huggingface_hkunlp/instructor-large, cohere_medium)

If using Llama, set the `EMBEDDINGS_NAME` to `huggingface_sentence-transformers/all-mpnet-base-v2` and be sure to download [this model](https://d3dg1063dc54p9.cloudfront.net/models/docsgpt-7b-f16.gguf) into the `models/` folder: `https://d3dg1063dc54p9.cloudfront.net/models/docsgpt-7b-f16.gguf`. 

Alternatively, if you wish to run Llama locally, you can run `setup.sh` and choose option 1 when prompted. You do not need to manually add the DocsGPT model mentioned above to your `models/` folder if you use `setup.sh`, as the script will manage that step for you.

That's it!

### Hosting everything locally and privately (for using our optimised open-source models)
If you are working with critical data and don't want anything to leave your premises.

Make sure you set `SELF_HOSTED_MODEL` as true in your `.env` variable, and for your `LLM_NAME`, you can use anything that is on Hugging Face.
