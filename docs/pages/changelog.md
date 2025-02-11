---
title: 'Changelog'
---
## Launching Web App
**Note**: Make sure you have Docker installed

**On macOS or Linux:**
Just run the following command:

```bash
./setup.sh
```

This command will install all the necessary dependencies and provide you with an option to use our LLM API, download the local model or use OpenAI.

If you prefer to follow manual steps, refer to this guide:

1. Open and download this repository with 
   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   ```
2. Create a `.env` file in your root directory and set the env variables.
   It should look like this inside:

   ```
   LLM_NAME=[docsgpt or openai or others] 
   API_KEY=[if LLM_NAME is openai]
   ```

   See optional environment variables in the [/application/.env_sample](https://github.com/arc53/DocsGPT/blob/main/application/.env_sample) file.
   
3. Run the following commands:
   ```bash
   docker compose -f deployment/docker-compose.yaml up
   ```
4. Navigate to http://localhost:5173/.

To stop, simply press **Ctrl + C**.

**For WINDOWS:**

1. Open and download this repository with 
   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   ```

2. Create a `.env` file in your root directory and set the env variables.
   It should look like this inside:

   ```
   LLM_NAME=[docsgpt or openai or others] 
   API_KEY=[if LLM_NAME is openai]
   ```

   See optional environment variables in the [/application/.env_sample](https://github.com/arc53/DocsGPT/blob/main/application/.env_sample) file.

3. Run the following command:

   ```bash
   docker compose -f deployment/docker-compose.yaml up
   ```
4. Navigate to http://localhost:5173/.
5. To stop the setup, just press **Ctrl + C** in the WSL terminal

**Important:** Ensure that Docker is installed and properly configured on your Windows system for these steps to work.
