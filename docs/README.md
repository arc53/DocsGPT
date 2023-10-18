# 📚 Setting Up the DocsGPT Repository Locally

## 📝 Summary

This guide will walk you through the process of setting up the DocsGPT repository on your local machine. You'll be able to view and edit the documentation offline.

## 1. 📥 Clone the DocsGPT Repository

```bash
git clone https://github.com/arc53/DocsGPT.git
```

## 2. 📂 Navigate to the Docs Folder

```bash
cd DocsGPT/docs
```

The `docs` folder contains the markdown files that make up the documentation. Notable files in this folder include:

- `index.mdx`: The main documentation file.
- `_app.js`: This file is used to customize the default Next.js application shell.
- `theme.config.jsx`: This file is for configuring the Nextra theme for the documentation.

## 3. 🧐 Verify Node.js and npm Installation

Make sure you have Node.js and npm installed. You can check their versions by running:

```bash
node --version
npm --version
```

## 4. ⬇️ Install Node.js and npm (If Not Installed)

If Node.js and npm are not installed, download them from the respective official websites.

## 5. 🚀 Install Yarn

Once you have Node.js and npm installed, proceed to install Yarn, another package manager for managing project dependencies:

```bash
npm install --global yarn
```

## 6. 📦 Install Project Dependencies

Install the project dependencies using Yarn:

```bash
yarn install
```

## 7. 🚀 Start the Local Server

After the successful installation of the project dependencies, start the local server:

```bash
yarn dev
```

Now, you should be able to view the docs on your local environment by visiting `http://localhost:5000`. You can explore the different markdown files and make changes as needed.

**Note:** This guide assumes you have Node.js and npm installed. It involves running a local server using Yarn and viewing the documentation offline. If you encounter any issues, please verify your Node.js and npm installations and ensure Yarn is installed correctly.
