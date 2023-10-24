## Chatwoot Extension Setup Guide

### Step 1: Prepare and Start DocsGPT

- **Launch DocsGPT**: Follow the instructions in our [DocsGPT Wiki](https://github.com/arc53/DocsGPT/wiki) to start DocsGPT. Make sure to load your documentation.

### Step 2: Get Access Token from Chatwoot

- Go to Chatwoot.
- In your profile settings (located at the bottom left), scroll down and copy the **Access Token**.

### Step 3: Set Up Chatwoot Extension

- Navigate to `/extensions/chatwoot`.
- Copy the `.env_sample` file and create a new file named `.env`.
- Fill in the values in the `.env` file as follows:

```env
docsgpt_url=<Docsgpt_API_URL>
chatwoot_url=<Chatwoot_URL>
docsgpt_key=<OpenAI_API_Key or Other_LLM_Key>
chatwoot_token=<Token from Step 2>
```

### Step 4: Start the Extension

- Use the command `flask run` to start the extension.

### Step 5: Optional - Extra Validation

- In app.py, uncomment lines 12-13 and 71-75.
- Add the following lines to your .env file:
```account_id=(optional) 1
assignee_id=(optional) 1
```
These Chatwoot values help ensure you respond to the correct widget and handle questions assigned to a specific user.

### Stopping Bot Responses for Specific User or Session

- If you want the bot to stop responding to questions for a specific user or session, add a label `human-requested` in your conversation.

### Additional Notes

- For further details on training on other documentation, refer to our [wiki](https://github.com/arc53/DocsGPT/wiki/How-to-train-on-other-documentation).