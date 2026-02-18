const nextra = require('nextra').default;

const withNextra = nextra({
  // Nextra v4 config lives in app/layout + theme.config.jsx
});

module.exports = withNextra({
  reactStrictMode: true,
});
