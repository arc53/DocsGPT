# Welcome to DocsGPT Contributing Guidelines

Thank you for choosing to contribute to DocsGPT! We are all very grateful! 

### [🎉 Join the Hacktoberfest with DocsGPT and Earn a Free T-shirt! 🎉](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md)

# We accept different types of contributions

📣 Discussions - Engage in conversations, start new topics, or help answer questions.

🐞 Issues - This is where we keep track of tasks. It could be bugs,fixes or suggestions for new features.

🛠️ Pull requests - Suggest changes to our repository, either by working on existing issues or adding new features.

📚 Wiki - This is where our documentation resides.


## 🐞 Issues and Pull requests

We value contributions in the form of discussions or suggestions. We recommend taking a look at existing issues and our [roadmap](https://github.com/orgs/arc53/projects/2).

If you're interested in contributing code, here are some important things to know:

We have a frontend built with React (Vite) and a backend in Python.

### If you are looking to contribute to frontend (⚛️React, Vite):

- The current frontend is being migrated from `/application` to `/frontend` with a new design, so please contribute to the new one.
- Check out this [milestone](https://github.com/arc53/DocsGPT/milestone/1) and its issues.
- The Figma design can be found [here](https://www.figma.com/file/OXLtrl1EAy885to6S69554/DocsGPT?node-id=0%3A1&t=hjWVuxRg9yi5YkJ9-1).

Please try to follow the guidelines.

### If you are looking to contribute to Backend (🐍 Python):
- Review our issues and contribute to /application or /scripts (please disregard old ingest_rst.py and ingest_rst_sphinx.py files; they will be deprecated soon).
- All new code should be covered with unit tests ([pytest](https://github.com/pytest-dev/pytest)). Please find tests under [`/tests`](https://github.com/arc53/DocsGPT/tree/main/tests) folder.
- Before submitting your Pull Request, ensure it can be queried after ingesting some test data.
  
### Testing

To run unit tests from the root of the repository, execute:
```
python -m pytest
```

### Workflow:
Fork the repository, make your changes on your forked version, and then submit those changes as a pull request.

## Questions/collaboration
Feel free to join our [Discord](https://discord.gg/n5BX8dh8rU). We're very friendly and welcoming to new contributors, so don't hesitate to reach out.
# Thank you so much for considering contributing to DocsGPT!🙏
