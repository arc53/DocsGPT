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
   ```
2. Create a `.env` file in your root directory and set your `API_KEY` with your [OpenAI API key](https://platform.openai.com/account/api-keys). (optional in case you want to use OpenAI)
3. Run the following commands:
   ```bash
   docker-compose build && docker-compose up
   ```
4. Navigate to http://localhost:5173/.

To stop, simply press **Ctrl + C**.

**For WINDOWS:**

To run the setup on Windows, you have two options: using the Windows Subsystem for Linux (WSL) or using Git Bash or Command Prompt.

**Option 1: Using Windows Subsystem for Linux (WSL):**

1. Install WSL if you haven't already. You can follow the official Microsoft documentation for installation: (https://learn.microsoft.com/en-us/windows/wsl/install).
2. After setting up WSL, open the WSL terminal.
3. Clone the repository and create the `.env` file:
   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   echo "API_KEY=Yourkey" > .env
   echo "VITE_API_STREAMING=true" >> .env
   ```
4. Run the following command to start the setup with Docker Compose:
   ```bash
   ./run-with-docker-compose.sh
   ```
6. Open your web browser and navigate to http://localhost:5173/.
7. To stop the setup, just press **Ctrl + C** in the WSL terminal

**Option 2: Using Git Bash or Command Prompt (CMD):**

1. Install Git for Windows if you haven't already. Download it from the official website: (https://gitforwindows.org/).
2. Open Git Bash or Command Prompt.
3. Clone the repository and create the `.env` file:
   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   echo "API_KEY=Yourkey" > .env
   echo "VITE_API_STREAMING=true" >> .env
   ```
4. Run the following command to start the setup with Docker Compose:
   ```bash
   ./run-with-docker-compose.sh
   ```
5. Open your web browser and navigate to http://localhost:5173/.
6. To stop the setup, just press **Ctrl + C** in the Git Bash or Command Prompt terminal.

These steps should help you set up and run the project on Windows using either WSL or Git Bash/Command Prompt. 
**Important:** Ensure that Docker is installed and properly configured on your Windows system for these steps to work.
