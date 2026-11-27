import { Analytics } from '@vercel/analytics/react';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { Inter } from 'next/font/google';

import { DocsGPTChatWidget } from '../components/DocsGPTChatWidget';
import { HOME_TITLE, SITE_NAME, SITE_URL } from '../page-meta';

import './global.css';
import './brand.css';

// The DocsGPT app's typeface, self-hosted by next/font.
const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });

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
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: '48x48' },
      { url: '/favicon.svg', type: 'image/svg+xml' },
      { url: '/favicon-96x96.png', type: 'image/png', sizes: '96x96' },
    ],
    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180' }],
  },
  manifest: '/site.webmanifest',
  other: { 'apple-mobile-web-app-title': 'DocsGPT Docs' },
};

// The browser chrome colour on mobile: the page background (app/theme.css).
export const viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#222327' },
  ],
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" dir="ltr" className={inter.variable} suppressHydrationWarning>
      <body className="flex min-h-screen flex-col">
        {/* The sidebar layouts are app/(docs)/layout.jsx and app/API/endpoints/layout.jsx. */}
        <RootProvider theme={{ defaultTheme: 'dark' }}>{children}</RootProvider>
        <DocsGPTChatWidget />
        <Analytics />
      </body>
    </html>
  );
}
