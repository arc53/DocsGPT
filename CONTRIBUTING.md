# Welcome to DocsGPT Contributing Guidelines

Thank you for choosing to contribute to DocsGPT! We are all very grateful! 

# We accept different types of contributions

📣 **Discussions** - Engage in conversations, start new topics, or help answer questions.

🐞 **Issues** - This is where we keep track of tasks. It could be bugs, fixes or suggestions for new features.

🛠️ **Pull requests** - Suggest changes to our repository, either by working on existing issues or adding new features.

📚 **Wiki** - This is where our documentation resides.


## 🐞 Issues and Pull requests

- We value contributions in the form of discussions or suggestions. We recommend taking a look at existing issues and our [roadmap](https://github.com/orgs/arc53/projects/2).


- If you're interested in contributing code, here are some important things to know:

- We have a frontend built on React (Vite) and a backend in Python.

  
Before creating issues, please check out how the latest version of our app looks and works by launching it via [Quickstart](https://github.com/arc53/DocsGPT#quickstart) the version on our live demo is slightly modified with login. Your issues should relate to the version you can launch via [Quickstart](https://github.com/arc53/DocsGPT#quickstart).

### 👨‍💻 If you're interested in contributing code, here are some important things to know:

For instructions on setting up a development environment, please refer to our [Development Deployment Guide](https://docs.docsgpt.cloud/Deploying/Development-Environment).

Tech Stack Overview:

- 🌐 Frontend: Built with React (Vite) ⚛️,

- 🖥 Backend: Developed in Python 🐍

### 🌐 Frontend Contributions (⚛️ React, Vite)

*   The updated Figma design can be found [here](https://www.figma.com/file/OXLtrl1EAy885to6S69554/DocsGPT?node-id=0%3A1&t=hjWVuxRg9yi5YkJ9-1).  Please try to follow the guidelines.
*   **Coding Style:** We follow a strict coding style enforced by ESLint and Prettier. Please ensure your code adheres to the configuration provided in our repository's `fronetend/.eslintrc.js` file.  We recommend configuring your editor with ESLint and Prettier to help with this.
* **Component Structure:** Strive for small, reusable components.  Favor functional components and hooks over class components where possible.
* **State Management** If you need to add stores, please use Redux.

### 🖥 Backend Contributions (🐍 Python)

- Review our issues and contribute to [`/application`](https://github.com/arc53/DocsGPT/tree/main/application) 
- All new code should be covered with unit tests ([pytest](https://github.com/pytest-dev/pytest)). Please find tests under [`/tests`](https://github.com/arc53/DocsGPT/tree/main/tests) folder.
- Before submitting your Pull Request, ensure it can be queried after ingesting some test data.
- **Coding Style:** We adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code. We use `ruff` as our linter and code formatter.  Please ensure your code is formatted correctly and passes `ruff` checks before submitting.
- **Type Hinting:**  Please use type hints for all function arguments and return values. This improves code readability and helps catch errors early.  Example:

    ```python
    def my_function(name: str, count: int) -> list[str]:
        ...
    ```
- **Docstrings:**  All functions and classes should have docstrings explaining their purpose, parameters, and return values.  We prefer the [Google style docstrings](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html). Example:

    ```python
    def my_function(name: str, count: int) -> list[str]:
        """Does something with a name and a count.

        Args:
            name: The name to use.
            count: The number of times to do it.

        Returns:
            A list of strings.
        """
        ...
    ```
  
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
      ``` shell
      git clone https://github.com/<your-github-username>/DocsGPT.git
      ```

3. **Keep your Fork in Sync:**
   - Before you make any changes, make sure that your fork is in sync to avoid merge conflicts using:
     ```shell
     git remote add upstream https://github.com/arc53/DocsGPT.git
     git pull upstream main
     ```

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
# Thank you so much for considering to contributing DocsGPT!🙏
