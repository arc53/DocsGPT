# Welcome to DocsGPT Contributing guideline

Thank you for choosing this project to contribute to, we are all very grateful!

### [🎉 Join the Hacktoberfest with DocsGPT and Earn a Free T-shirt! 🎉](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md)

# We accept different types of contributions

📣 Discussions - where you can start a new topic or answer some questions

🐞 Issues - This is how we track tasks, sometimes it is bugs that need fixing, and sometimes it is new features

🛠️ Pull requests - This is how you can suggest changes to our repository, to work on existing issues or add new features

📚 Wiki - where we have our documentation


## 🐞 Issues and Pull requests

We value contributions to our issues in the form of discussion or suggestion, we recommend that you check out existing issues and our [Roadmap](https://github.com/orgs/arc53/projects/2)

If you want to contribute by writing code there are a few things that you should know before doing it:
We have frontend (React, Vite) and Backend (python)

### If you are looking to contribute to Frontend (⚛️React, Vite):
The current frontend is being migrated from /application to /frontend with a new design, so please contribute to the new one. Check out this [Milestone](https://github.com/arc53/DocsGPT/milestone/1) and its issues also [Figma](https://www.figma.com/file/OXLtrl1EAy885to6S69554/DocsGPT?node-id=0%3A1&t=hjWVuxRg9yi5YkJ9-1)
Please try to follow the guidelines.

### If you are looking to contribute to Backend (🐍Python):
* Check out our issues, and contribute to /application or /scripts (ignore old  ingest_rst.py ingest_rst_sphinx.py files, they will be deprecated soon)
* All new code should be covered with unit tests ([pytest](https://github.com/pytest-dev/pytest)). Please find tests under [/tests](https://github.com/arc53/DocsGPT/tree/main/tests) folder.
* Before submitting your PR make sure that after you ingested some test data it is queryable.

### Testing
To run unit tests, from the root of the repository execute:
```
python -m pytest
```

### Workflow:
Create a fork, make changes on your forked repository, and submit changes in the form of a pull request.

## Questions/collaboration
Please join our [Discord](https://discord.gg/n5BX8dh8rU) don't hesitate, we are very friendly and welcoming to new contributors.

# Thank you so much for considering contributing to DocsGPT!🙏
