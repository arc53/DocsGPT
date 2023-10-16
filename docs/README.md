# nextra-docsgpt

## Setting Up Docs Folder of DocsGPT Locally

### 1. Clone the DocsGPT repository:

```
git clone https://github.com/arc53/DocsGPT.git

```
### 2. Navigate to the docs folder:

```
cd DocsGPT/docs

```
The docs folder contains the markdown files that make up the documentation. The majority of the files are in the pages directory. Some notable files in this folder include:

`index.mdx`: The main documentation file.
`_app.js`: This file is used to customize the default Next.js application shell.
`theme.config.jsx`: This file is for configuring the Nextra theme for the documentation.

### 3. Verify that you have Node.js and npm installed in your system. You can check by running:

```
node --version
npm --version

```
### 4. If not installed, download Node.js and npm from the respective official websites.

### 5. Once you have Node.js and npm running, proceed to install yarn - another package manager that helps to manage project dependencies:

```
npm install --global yarn

```
### 6. Install the project dependencies using yarn:

```
yarn install

```
### 7. After the successful installation of the project dependencies, start the local server:

```
yarn dev

```

- Now, you should be able to view the docs on your local environment by visiting `http://localhost:5000`. You can explore the different markdown files and make changes as you see fit.

- Footnotes: This guide assumes you have Node.js and npm installed. The guide involves running a local server using yarn, and viewing the documentation offline. If you encounter any issues, it may be worth verifying your Node.js and npm installations and whether you have installed yarn correctly.
