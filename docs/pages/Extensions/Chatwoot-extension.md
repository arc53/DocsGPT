### To start chatwoot extension:
1. Prepare and start the DocsGPT itself (load your documentation too). Follow our [wiki](https://github.com/arc53/DocsGPT/wiki) to start it and to [ingest](https://github.com/arc53/DocsGPT/wiki/How-to-train-on-other-documentation) data.
2. Go to chatwoot, **Navigate** to your profile (bottom left), click on profile settings, scroll to the bottom and copy **Access Token**.
3. Navigate to `/extensions/chatwoot`. Copy `.env_sample` and create `.env` file.
4. Fill in the values.

```
docsgpt_url=<docsgpt_api_url>
chatwoot_url=<chatwoot_url>
docsgpt_key=<openai_api_key or other llm key>
chatwoot_token=<from part 2>
```

5. Start with `flask run` command.

If you want for bot to stop responding to questions for a specific user or session just add label `human-requested` in your conversation.


### Optional (extra validation)
In `app.py` uncomment lines 12-13 and 71-75

in your `.env` file add:

```
account_id=(optional) 1
assignee_id=(optional) 1
```

Those are chatwoot values and will allow you to check if you are responding to correct widget and responding to questions assigned to specific user.