import Image from 'next/image';
import { Analytics } from '@vercel/analytics/react';
import { Banner, Head } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import { Footer, Layout, Navbar } from 'nextra-theme-docs';
import 'nextra-theme-docs/style.css';

import CuteLogo from '../public/cute-docsgpt.png';
import themeConfig from '../theme.config';

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
        <Image src={CuteLogo} alt="DocsGPT logo" width={28} height={28} />
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
        <link
          rel="apple-touch-icon"
          sizes="180x180"
          href="/favicons/apple-touch-icon.png"
        />
        <link rel="icon" type="image/png" sizes="32x32" href="/favicons/favicon-32x32.png" />
        <link rel="icon" type="image/png" sizes="16x16" href="/favicons/favicon-16x16.png" />
        <link rel="manifest" href="/favicons/site.webmanifest" />
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
        <Analytics />
      </body>
    </html>
  );
}
