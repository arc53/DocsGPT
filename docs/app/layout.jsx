import { Analytics } from '@vercel/analytics/react';
import { Banner, Head } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import { Footer, Layout, Navbar } from 'nextra-theme-docs';
import 'nextra-theme-docs/style.css';

import { DocsGPTChatWidget } from '../components/DocsGPTChatWidget';
import themeConfig from '../theme.config';

import './brand.css';

const github = 'https://github.com/arc53/DocsGPT';

export const metadata = {
  title: {
    default: 'DocsGPT Documentation',
    template: '%s - DocsGPT Documentation',
  },
  description:
    'Use DocsGPT to chat with your data. DocsGPT is a GPT-powered chatbot that can answer questions about your data.',
};

const navbar = (
  <Navbar
    logo={
      <div style={{ alignItems: 'center', display: 'flex', gap: '8px' }}>
        <img
          className="brand-logo brand-logo-light"
          src="/logo-b.svg"
          alt="DocsGPT logo"
        />
        <img className="brand-logo brand-logo-dark" src="/logo-w.svg" alt="" />
        <span style={{ fontWeight: 'bold', fontSize: 18 }}>DocsGPT Docs</span>
      </div>
    }
    projectLink={github}
    chatLink="https://discord.com/invite/n5BX8dh8rU"
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
    <a href="https://blog.docsgpt.cloud/" target="_blank" rel="noreferrer">
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
        <meta httpEquiv="Content-Language" content="en" />
      </Head>
      <body>
        <Layout
          banner={
            <Banner storageKey="docs-launch">
              <div className="flex justify-center items-center gap-2">
                Welcome to the new DocsGPT docs!
              </div>
            </Banner>
          }
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
