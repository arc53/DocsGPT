
# Slack Bot Configuration Guide

> **Note:** The following guidelines must be followed on the [Slack API website](https://api.slack.com/) for setting up your Slack app and generating the necessary tokens.

## Step-by-Step Instructions

### 1. Navigate to Your Apps
- Go to the Slack API page for apps and select **Create an App** from the “From Scratch” option.

### 2. App Creation
- Name your app and choose the workspace where you wish to add the assistant. 

### 3. Enabling Socket Mode
- Navigate to **Settings > Socket Mode** and enable **Socket Mode**. 
- This action will generate an App-level token. Select the `connections:write` scope and copy the App-level token for future use.

### 4. Socket Naming
- Assign a name to your socket as per your preference.

### 5. Basic Information Setup
- Go to **Basic Information** (under **Settings**) and configure the following:
  - Assistant name
  - App icon
  - Background color 

### 6. Bot Token and Permissions
- In the **OAuth & Permissions** option found under the **Features** section, retrieve the Bot Token. Save it for future usage.
- You will also need to add specific bot token scopes:
  - `app_mentions:read`
  - `assistant:write`
  - `chat:write`
  - `chat:write.public`
  - `im:history`

### 7. Enable Events
- From **Event Subscriptions**, enable events and add the following Bot User events:
  - `app_mention`
  - `assistant_thread_context_changed`
  - `assistant_thread_started`
  - `message.im`

### 8. Agent/Assistant Toggle
- In the **Features > Agent & Assistants** section, toggle on the Agent or Assistant option. 
- In the **Suggested Prompts** setting, leave it as `dynamic` (this is the default setting).

---

## Code-Side Configuration Guide

This section focuses on generating and setting up the necessary tokens in the `.env` file, using the `.env-example` as a template.

### Step 1: Generating Required Keys

1. **SLACK_APP_TOKEN**
   - Navigate to **Settings > Socket Mode** in the Slack API and enable **Socket Mode**.
   - Copy the App-level token generated (usually starts with `xapp-`).

2. **SLACK_BOT_TOKEN**
   - Go to **OAuth & Permissions** (under the **Features** section in Slack API).
   - Retrieve the **Bot Token** (starts with `xoxb-`).

3. **DOCSGPT_API_KEY**
   - Go to the **DocsGPT website**.
   - Navigate to **Settings > Chatbots > Create New** to generate a DocsGPT API Key.
   - Copy the generated key for use.

### Step 2: Creating and Updating the `.env` File

1. Create a new `.env` file in the root of your project (if it doesn’t already exist).
2. Use the `.env-example` as a reference and update the file with the following keys and values:

```bash
# .env file
SLACK_APP_TOKEN=xapp-your-generated-app-token
SLACK_BOT_TOKEN=xoxb-your-generated-bot-token
DOCSGPT_API_KEY=your-docsgpt-generated-api-key
```

Replace the placeholder values with the actual tokens generated from the Slack API and DocsGPT as per the steps outlined above.

---

This concludes the guide for both setting up the Slack API and configuring the `.env` file on the code side.
