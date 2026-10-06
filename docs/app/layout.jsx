import { Analytics } from '@vercel/analytics/react';
import { Head } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import { Footer, Layout, Navbar } from 'nextra-theme-docs';
import 'nextra-theme-docs/style.css';

import { DocsGPTChatWidget } from '../components/DocsGPTChatWidget';
import { FullLogo } from '../components/FullLogo';
import { HOME_TITLE, SITE_NAME, SITE_URL } from '../page-meta';
import themeConfig from '../theme.config';

import './brand.css';

const github = 'https://github.com/arc53/DocsGPT';

// Each page adds its own canonical URL, share card and description; see
// pageMetadata() in page-meta.js.
export const metadata = {
  metadataBase: new URL(SITE_URL),
  applicationName: SITE_NAME,
  title: {
    default: HOME_TITLE,
    template: `%s | ${SITE_NAME}`,
  },
  description:
    'DocsGPT is an open-source platform for building AI agents and assistants with document retrieval, tools, and multi-model support.',
};

const navbar = (
  <Navbar
    logo={
      <div className="brand">
        <FullLogo className="brand-logo" />
        <span className="brand-divider" aria-hidden="true" />
        <span className="brand-label">Docs</span>
      </div>
    }
    projectLink={github}
    chatLink="https://discord.gg/vN7YFfdMpj"
  />
);

const footer = (
  <Footer>
    <span>MIT {new Date().getFullYear()} © </span>
    <a href="https://www.docsgpt.cloud/" target="_blank" rel="noreferrer">
      DocsGPT
    </a>
    {' | '}
    <a href="https://github.com/arc53/DocsGPT" target="_blank" rel="noreferrer">
      GitHub
    </a>
    {' | '}
    <a href="https://www.docsgpt.cloud/blog" target="_blank" rel="noreferrer">
      Blog
    </a>
  </Footer>
);

export default async function RootLayout({ children }) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <Head>
        <link rel="icon" href="/favicon.ico" sizes="48x48" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <link
          rel="icon"
          href="/favicon-96x96.png"
          type="image/png"
          sizes="96x96"
        />
        <link
          rel="apple-touch-icon"
          href="/apple-touch-icon.png"
          sizes="180x180"
        />
        <link rel="manifest" href="/site.webmanifest" />
        <meta name="apple-mobile-web-app-title" content="DocsGPT Docs" />
      </Head>
      <body>
        <Layout
          navbar={navbar}
          footer={footer}
          pageMap={await getPageMap()}
          {...themeConfig}
        >
          {children}
        </Layout>
        <DocsGPTChatWidget />
        <Analytics />
      </body>
    </html>
  );
}
