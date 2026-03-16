const github = 'https://github.com/arc53/DocsGPT';
const isDevelopment = process.env.NODE_ENV === 'development';

const config = {
  docsRepositoryBase: `${github}/blob/main/docs`,
  darkMode: true,
  search: isDevelopment ? null : undefined,
  nextThemes: {
    defaultTheme: 'dark',
  },
  sidebar: {
    defaultMenuCollapseLevel: 1,
  },
  toc: {
    float: true,
  },
  editLink: 'Edit this page on GitHub',
};

export default config;
