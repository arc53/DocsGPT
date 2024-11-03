# LLM Document Analysis by [LexEU](https://www.lexeu.ai/) Competition

## 🏆 Competition Details:

Welcome to the LLM Document Analysis by [LexEU](https://www.lexeu.ai/) competition, part of Hacktoberfest! This challenge is designed for participants who can devise the best new retrieval or workflow method to analyze a document using EU laws.

### 🏅 Prizes:
- **1st Place:** $200 + Special Holopin
- **2nd Place:** $100 + Special Holopin
- **3rd Place:** $50 + Special Holopin
- **Top 3 Winners:** Special Holopin

### 📆 Timeline:
- **Competition Announcement:** 1st October
- **Deadline for Submissions:** 8th November
- **Results Announcement:** Early November

## 📜 How to Participate:

Participants are required to analyze a given test contract by scraping EU law data, storing it in a database, and retrieving only the relevant portions for analysis. The solution must be optimized for efficiency, using a maximum of 500k tokens.

### Steps to Participate:

1. **Download Test Contract:** You can download it via this [link](https://docs.google.com/document/d/198d7gFJbVWttkIS9ZRUs_PTKIjhsOUeR/edit?usp=sharing&ouid=107667025862106683614&rtpof=true&sd=true).
2. **Ingest EU Law Data:** Gather and store data in any format, it's available [here](https://eur-lex.europa.eu/browse/directories/legislation.html?displayProfile=lastConsDocProfile&classification=in-force).
3. **Optimized Data Retrieval:** Implement methods to retrieve only small, relevant portions of the law data for efficient analysis of the test contract. Try to create a custom retriever and a parser.
4. **Analyze the Contract:** Use your optimized retrieval method to analyze the test contract against the EU law data.
5. **Submission Criteria:** Your solution will be judged based on:
   - Amount of corrections/inconsistencies found
   - Number of tokens used (Maximum 500k tokens)
   - Your submission should be a fork of DocsGPT where all the ingestion and analysis steps can be replicated

### Submission Instructions:

1. **Submit Your Work:** Once you finish your analysis, submit your solution by filling out this [form](https://airtable.com/appikMaJwdHhC1SDP/pagLWdew2HKpEaBKr/form).
2. **Private Test Contract:** Your solution will also be benchmarked against a private test contract to validate its efficiency and effectiveness.
3. **Evaluation:** The winners will be evaluated based on the effectiveness of their solution in identifying corrections/inconsistencies and the number of tokens used in the process.

### Resources:

- **Documentation:** Refer to our [Documentation](https://docs.docsgpt.cloud/) for guidance.
- **Discord Support:** Join our [Discord](https://discord.gg/n5BX8dh8rU) server for support and discussions related to the competition.
- Try looking at existing [retrievers](https://github.com/arc53/DocsGPT/tree/main/application/retriever) and maybe creating a custom one
- Try looking at [worker.py](https://github.com/arc53/DocsGPT/blob/main/application/worker.py) which ingests data and creating a custom one for ingesting EU law

## 👥 Community and Support:

If you need assistance, feel free to join our [Discord](https://discord.gg/n5BX8dh8rU) server. We're here to help newcomers, so don't hesitate to jump in and ask questions!

## 📢 Announcement:
Stay tuned for updates, and good luck to all participants!

Thank you for participating in the LLM Document Analysis by LexEU competition. Your innovative solutions could not only win you prizes but also contribute significantly to the DocsGPT community. Happy coding! 🚀

---
