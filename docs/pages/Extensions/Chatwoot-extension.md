### To Start Chatwoot Extension:

1. **Prepare and Start DocsGPT:**
   - Launch DocsGPT using the instructions in our [wiki](https://github.com/arc53/DocsGPT/wiki).
   - Make sure to load your documentation.

2. **Get Access Token from Chatwoot:**
   - Navigate to Chatwoot.
   - Go to your profile (bottom left), click on profile settings.
   - Scroll to the bottom and copy the **Access Token**.

3. **Set Up Chatwoot Extension:**
   - Navigate to `/extensions/chatwoot`.
   - Copy `.env_sample` and create a `.env` file.
   - Fill in the values in the `.env` file:

     ```env
     docsgpt_url=<docsgpt_api_url>
     chatwoot_url=<chatwoot_url>
     docsgpt_key=<openai_api_key or other llm key>
     chatwoot_token=<from part 2>
     ```

4. **Start the Extension:**
   - Use the command `flask run` to start the extension.

5. **Optional: Extra Validation**
   - In `app.py`, uncomment lines 12-13 and 71-75.
   - Add the following lines to your `.env` file:

     ```env
     account_id=(optional) 1
     assignee_id=(optional) 1
     ```

     These Chatwoot values help ensure you respond to the correct widget and handle questions assigned to a specific user.

### Stopping Bot Responses for Specific User or Session:
- If you want the bot to stop responding to questions for a specific user or session, add a label `human-requested` in your conversation.

### Additional Notes:
- For further details on training on other documentation, refer to our [wiki](https://github.com/arc53/DocsGPT/wiki/How-to-train-on-other-documentation).
