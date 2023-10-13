# nextra-docsgpt
Nextra Docs Theme is a theme that includes almost everything you need to build a modern documentation website. It includes a top navigation bar, a search bar, a pages sidebar, a TOC sidebar, and other built-in components.

This website itself is built with the Nextra Docs Theme.

# Quick Start from Template

**Deploy to Vercel** 

You can start by creating your own Nextra site and deploying to Vercel by clicking the link:

<a href="https://vercel.com/new/clone"><img src="https://vercel.com/button" alt=""></a>

Vercel will fork the [Nextra Docs template](https://github.com/shuding/nextra-docs-template) and deploy the site for you. Once done, every commit in the repository will be deployed automatically.

## Fork the Template

You can also manually fork the [template repository](https://github.com/shuding/nextra-docs-template).

# Start as New Project
## 1) Install

To create a Nextra Docs site manually, you have to install **Next.js, React, Nextra, and Nextra Docs Theme**. In your project directory, run the following command to install the dependencies:

**npm**

```
npm i next react react-dom nextra nextra-theme-docs
```
**pnpm**

```
pnpm add next react react-dom nextra nextra-theme-docs
```
**yarn**

```
yarn add next react react-dom nextra nextra-theme-docs
```
**bun**

```
bun add next react react-dom nextra nextra-theme-docs
```



- **NOTE** :   If you already have Next.js installed in your project, you only need to install ```nextra``` and ```nextra-theme-docs``` as the add-ons.


## 2)Add Next.js Config
Create the following ```next.config.js``` file in your project’s root directory:

**next.config.js**
```
const withNextra = require('nextra')({
  theme: 'nextra-theme-docs',
  themeConfig: './theme.config.jsx'
})
 
module.exports = withNextra()
 
// If you have other Next.js configurations, you can pass them as the parameter:
// module.exports = withNextra({ /* other next.js config */ })

```

With the above configuration, Nextra can handle Markdown files in your Next.js project, with the specified theme. Other Nextra configurations can be found in [Guide](https://nextra.site/docs/guide).

## 3)Create Docs Theme Config

Lastly, create the corresponding ```theme.config.jsx``` file in your project’s root directory. This will be used to configure the Nextra Docs theme:

**theme.config.jsx**
```
export default {
  logo: <span>My Nextra Documentation</span>,
  project: {
    link: 'https://github.com/shuding/nextra'
  }
  // ... other theme options
}

```


Full theme configurations can be found [here](https://nextra.site/docs/docs-theme/theme-configuration).

## 4)Ready to Go!

Now, you can create your first MDX page as ```pages/index.mdx```:

**pages/index.mdx**
```

# Welcome to Nextra
 
Hello, world!

```

And run the ```next```  or  ```next dev```  command specified in package.jsonto start developing the project! 🎉

