const nextra = require('nextra').default;

const withNextra = nextra({
  defaultShowCopyCode: true,
});

module.exports = withNextra({
  reactStrictMode: true,
  async redirects() {
    return [
      // Retired hosting guides: the installer's --domain flow covers any VM.
      { source: '/Deploying/Hosting-the-app', destination: '/Deploying', permanent: true },
      { source: '/Deploying/Amazon-Lightsail', destination: '/Deploying', permanent: true },
      { source: '/Deploying/Railway', destination: '/Deploying', permanent: true },
    ];
  },
});
