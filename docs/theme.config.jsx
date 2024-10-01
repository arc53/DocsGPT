import Image from 'next/image'
import { Analytics } from '@vercel/analytics/react';

const github = 'https://github.com/arc53/DocsGPT';




import { useConfig, useTheme } from 'nextra-theme-docs';
import CuteLogo from './public/cute-docsgpt.png';
const Logo = ({ height, width }) => {
  const { theme } = useTheme();
  return (
    <div style={{ alignItems: 'center', display: 'flex', gap: '8px' }}>
       <Image src={CuteLogo} alt="DocsGPT logo" width={width} height={height} />

      <span style={{ fontWeight: 'bold', fontSize: 18 }}>DocsGPT Docs</span>


    </div>
  );
};

const config = {
  docsRepositoryBase: `${github}/blob/main/docs`,
  chat: {
    link: 'https://discord.com/invite/n5BX8dh8rU',
  },
  banner: {
    key: 'docs-launch',
    text: (
      <div className="flex justify-center items-center gap-2">
        Welcome to the new DocsGPT 🦖 docs! 👋
      </div>
    ),
  },
  toc: {
    float: true,
  },
  project: {
    link: github,
  },
  darkMode: true,
  nextThemes: {
    defaultTheme: 'dark',
  },
  primaryHue: {
    dark: 207,
    light: 212,
  },
  footer: {
    text: `MIT ${new Date().getFullYear()} © DocsGPT`,
  },
  logo() {
    return (
      <div className="flex items-center gap-2">
        <Logo width={28} height={28} />
      </div>
    );
  },
  useNextSeoProps() {
    return {
      titleTemplate: `%s - DocsGPT Documentation`,
    };
  },

  head() {
    const { frontMatter } = useConfig();
    const { theme } = useTheme();
    const title = frontMatter?.title || 'Chat with your data with DocsGPT';
    const description =
      frontMatter?.description ||
      'Use DocsGPT to chat with your data. DocsGPT is a GPT powered chatbot that can answer questions about your data.'
    const image = '/cute-docsgpt.png';

    const composedTitle = `${title} – DocsGPT Documentation`;

    return (
      <>
        <link
          rel="apple-touch-icon"
          sizes="180x180"
          href={`/favicons/apple-touch-icon.png`}
        />
        <link
          rel="icon"
          type="image/png"
          sizes="32x32"
          href={`/favicons/favicon-32x32.png`}
        />
        <link
          rel="icon"
          type="image/png"
          sizes="16x16"
          href={`/favicons/favicon-16x16.png`}
        />
        <meta name="theme-color" content="#ffffff" />
        <meta name="msapplication-TileColor" content="#00a300" />
        <link rel="manifest" href={`/favicons/site.webmanifest`} />
        <meta httpEquiv="Content-Language" content="en" />
        <meta name="title" content={composedTitle} />
        <meta name="description" content={description} />

        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:site" content="@ATushynski" />
        <meta name="twitter:image" content={image} />

        <meta property="og:description" content={description} />
        <meta property="og:title" content={composedTitle} />
        <meta property="og:image" content={image} />
        <meta property="og:type" content="website" />
        <meta
          name="apple-mobile-web-app-title"
          content="DocsGPT Documentation"
        />

      </>
    );
  },
  sidebar: {
    defaultMenuCollapseLevel: 1,
    titleComponent: ({ title, type }) =>
      type === 'separator' ? (
        <div className="flex items-center gap-2">
          <Logo height={10} width={10} />
          {title}
            <Analytics />
        </div>

      ) : (
        <>{title}
        <Analytics />
        </>

      ),
  },

  gitTimestamp: ({ timestamp }) => (
    <>Last updated on {timestamp.toLocaleDateString()}</>
  ),
};

export default config;