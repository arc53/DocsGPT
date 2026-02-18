const nextra = require('nextra').default;

const withNextra = nextra({
  defaultShowCopyCode: true,
});

module.exports = withNextra({
  reactStrictMode: true,
});
