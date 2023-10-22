# Welcome to DocsGPT Contributing Guidelines

Thank you for choosing to contribute to DocsGPT! We are all very grateful! 

### [🎉 Join the Hacktoberfest with DocsGPT and Earn a Free T-shirt! 🎉](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md)

# We accept different types of contributions

📣 **Discussions** - Engage in conversations, start new topics, or help answer questions.

🐞 **Issues** - This is where we keep track of tasks. It could be bugs,fixes or suggestions for new features.

🛠️ **Pull requests** - Suggest changes to our repository, either by working on existing issues or adding new features.

📚 **Wiki** - This is where our documentation resides.


## 🐞 Issues and Pull requests

We value contributions in the form of discussions or suggestions. We recommend taking a look at existing issues and our [roadmap](https://github.com/orgs/arc53/projects/2).

Before creating issues, please check out how the latest version of our app looks and works by launching it via [Quickstart](https://github.com/arc53/DocsGPT#quickstart) the version on our live demo is slightly modified with login. Your issues should relate to the version that you can launch via [Quickstart](https://github.com/arc53/DocsGPT#quickstart).

### 👨‍💻 If you're interested in contributing code, here are some important things to know:

Tech Stack Overview:

- 🌐 Frontend: Built with React (Vite) ⚛️,

- 🖥 Backend: Developed in Python 🐍

### 🌐 If you are looking to contribute to frontend (⚛️React, Vite):

- The current frontend is being migrated from [`/application`](https://github.com/arc53/DocsGPT/tree/main/application) to [`/frontend`](https://github.com/arc53/DocsGPT/tree/main/frontend) with a new design, so please contribute to the new one.
- Check out this [milestone](https://github.com/arc53/DocsGPT/milestone/1) and its issues.
- The updated Figma design can be found [here](https://www.figma.com/file/OXLtrl1EAy885to6S69554/DocsGPT?node-id=0%3A1&t=hjWVuxRg9yi5YkJ9-1).

Please try to follow the guidelines.

### 🖥 If you are looking to contribute to Backend (🐍 Python):

- Review our issues and contribute to [`/application`](https://github.com/arc53/DocsGPT/tree/main/application) or [`/scripts`](https://github.com/arc53/DocsGPT/tree/main/scripts) (please disregard old [`ingest_rst.py`](https://github.com/arc53/DocsGPT/blob/main/scripts/old/ingest_rst.py) [`ingest_rst_sphinx.py`](https://github.com/arc53/DocsGPT/blob/main/scripts/old/ingest_rst_sphinx.py) files; they will be deprecated soon).
- All new code should be covered with unit tests ([pytest](https://github.com/pytest-dev/pytest)). Please find tests under [`/tests`](https://github.com/arc53/DocsGPT/tree/main/tests) folder.
- Before submitting your Pull Request, ensure it can be queried after ingesting some test data.
  
### Testing

To run unit tests from the root of the repository, execute:
```
python -m pytest
```

## Workflow 📈

Here's a step-by-step guide on how to contribute to DocsGPT:

1. **Fork the Repository:**
   - Click the "Fork" button at the top-right of this repository to create your fork.

2. **Clone the Forked Repository:**
   - Clone the repository using:
      ''' shell
      git clone https://github.com/<your-github-username>/DocsGPT.git
      '''

3. **Keep your Fork in Sync:**
   - Before you make any changes, make sure that your fork is in sync to avoid merge conflicts using:
   '''shell
   git remote add upstream https://github.com/arc53/DocsGPT.git
   git pull upstream master
   '''

4. **Create and Switch to a New Branch:**
   - Create a new branch for your contribution using:
     ```shell
     git checkout -b your-branch-name
     ```

5. **Make Changes:**
   - Make the required changes in your branch.

6. **Add Changes to the Staging Area:**
   - Add your changes to the staging area using:
     ```shell
     git add .
     ```

7. **Commit Your Changes:**
   - Commit your changes with a descriptive commit message using:
     ```shell
     git commit -m "Your descriptive commit message"
     ```

8. **Push Your Changes to the Remote Repository:**
   - Push your branch with changes to your fork on GitHub using:
     ```shell
     git push origin your-branch-name
     ```

9. **Submit a Pull Request (PR):**
   - Create a Pull Request from your branch to the main repository. Make sure to include a detailed description of your changes and reference any related issues.

10. **Collaborate:**
   - Be responsive to comments and feedback on your PR.
   - Make necessary updates as suggested.
   - Once your PR is approved, it will be merged into the main repository.

11. **Testing:**
   - Before submitting a Pull Request, ensure your code passes all unit tests.
   - To run unit tests from the root of the repository, execute:
     ```shell
     python -m pytest
     ```

*Note: You should run the unit test only after making the changes to the backend code.*

12. **Questions and Collaboration:**
    - Feel free to join our Discord. We're very friendly and welcoming to new contributors, so don't hesitate to reach out.

Thank you for considering contributing to DocsGPT! 🙏

## Questions/collaboration
Feel free to join our [Discord](https://discord.gg/n5BX8dh8rU). We're very friendly and welcoming to new contributors, so don't hesitate to reach out.
# Thank you so much for considering to contribute DocsGPT!🙏
