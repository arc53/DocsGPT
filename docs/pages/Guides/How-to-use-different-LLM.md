# Setting Up Local Language Models for Your App

Your app relies on two essential models: Embeddings and Text Generation. While OpenAI's default models work seamlessly, you have the flexibility to switch providers or even run the models locally.

## Step 1: Configure Environment Variables

Navigate to the `.env` file or set the following environment variables:

```env
LLM_NAME=<your Text Generation model>
API_KEY=<API key for Text Generation>
EMBEDDINGS_NAME=<LLM for Embeddings>
EMBEDDINGS_KEY=<API key for Embeddings>
VITE_API_STREAMING=<true or false>
```

You can omit the keys if users provide their own. Ensure you set `LLM_NAME` and `EMBEDDINGS_NAME`.

## Step 2: Choose Your Models

**Options for `LLM_NAME`:**
- openai ([More details](https://platform.openai.com/docs/models))
- anthropic ([More details](https://docs.anthropic.com/claude/reference/selecting-a-model))
- manifest ([More details](https://python.langchain.com/docs/integrations/llms/manifest))
- cohere ([More details](https://docs.cohere.com/docs/llmu))
- llama.cpp ([More details](https://python.langchain.com/docs/integrations/llms/llamacpp))
- huggingface (Arc53/DocsGPT-7B by default)
- sagemaker ([Mode details](https://aws.amazon.com/sagemaker/))


Note: for huggingface you can choose any model inside application/llm/huggingface.py or pass llm_name on init, loads   

**Options for `EMBEDDINGS_NAME`:**
- openai_text-embedding-ada-002
- huggingface_sentence-transformers/all-mpnet-base-v2
- huggingface_hkunlp/instructor-large
- cohere_medium

If you want to be completely local, set `EMBEDDINGS_NAME` to `huggingface_sentence-transformers/all-mpnet-base-v2`. 

For llama.cpp Download the required model and place it in the `models/` folder.

Alternatively, for local Llama setup, run `setup.sh` and choose option 1. The script handles the DocsGPT model addition.

## Step 3: Local Hosting for Privacy

If working with sensitive data, host everything locally by setting `LLM_NAME`, llama.cpp or huggingface, use any model available on Hugging Face, for llama.cpp you need to convert it into gguf format.
That's it! Your app is now configured for local and private hosting, ensuring optimal security for critical data.
