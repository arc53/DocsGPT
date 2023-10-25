# 📚 Setting Up the DocsGPT Repository Locally

## 📝 Overview

This guide provides step-by-step instructions for setting up the DocsGPT repository on your local machine, allowing you to access and edit the documentation offline.

## 1. 📥 Clone the DocsGPT Repository

To get started, clone the DocsGPT repository from the following URL:

```bash
git clone https://github.com/arc53/DocsGPT.git
```

## 2. 📂 Navigate to the Docs Folder

Once the repository is cloned, navigate to the `docs` folder using the following command:

```bash
cd DocsGPT/docs
```

Within the `docs` folder, you will find several important files, including:

- `index.mdx`: The primary documentation file.
- `_app.js`: Used to customize the default Next.js application shell.
- `theme.config.jsx`: For configuring the Nextra theme for the documentation.

## 3. 🧐 Verify Node.js and npm Installation

Before proceeding, confirm that you have Node.js and npm installed. You can check their versions by running the following commands:

```bash
node --version
npm --version
```

## 4. ⬇️ Install Node.js and npm (If Not Installed)

If Node.js and npm are not installed on your system, download and install them from the official websites.

## 5. 🚀 Install Yarn

After successfully installing Node.js and npm, proceed to install Yarn, an additional package manager for managing project dependencies:

```bash
npm install --global yarn
```

## 6. 📦 Install Project Dependencies

To install the project's required dependencies, use Yarn as follows:

```bash
yarn install
```

## 7. 🚀 Start the Local Server

Upon the successful installation of project dependencies, start the local server by running the following command:

```bash
yarn dev
```

With the local server running, you can access the documentation on your local environment by visiting `http://localhost:5000`. Here, you can explore various markdown files and make necessary changes.

**Note:** This guide assumes that you have Node.js and npm installed on your machine. It involves setting up a local server using Yarn to access and edit the documentation offline. In case of any issues, please ensure that your Node.js and npm installations are correct and that Yarn is properly installed.

