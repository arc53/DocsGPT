import { DocsLayout } from 'fumadocs-ui/layouts/docs';

import { FullLogo } from './FullLogo';

const github = 'https://github.com/arc53/DocsGPT';
const landing = 'https://www.docsgpt.cloud/';

function DiscordIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" width="20" height="20">
      <path d="M20.32 4.37a19.8 19.8 0 0 0-4.89-1.52.07.07 0 0 0-.08.04c-.21.38-.44.87-.6 1.25a18.27 18.27 0 0 0-5.49 0 12.64 12.64 0 0 0-.62-1.25.08.08 0 0 0-.08-.04 19.74 19.74 0 0 0-4.89 1.52.07.07 0 0 0-.03.03C.53 9.05-.32 13.58.1 18.06a.08.08 0 0 0 .03.06 19.9 19.9 0 0 0 5.99 3.03.08.08 0 0 0 .08-.03c.46-.63.87-1.3 1.23-1.99a.08.08 0 0 0-.04-.11 13.1 13.1 0 0 1-1.87-.89.08.08 0 0 1-.01-.13l.37-.29a.07.07 0 0 1 .08-.01c3.93 1.79 8.18 1.79 12.06 0a.07.07 0 0 1 .08.01l.37.29a.08.08 0 0 1-.01.13c-.6.35-1.22.65-1.87.89a.08.08 0 0 0-.04.11c.36.7.77 1.36 1.22 1.99a.08.08 0 0 0 .08.03 19.84 19.84 0 0 0 6-3.03.08.08 0 0 0 .03-.05c.5-5.18-.84-9.67-3.55-13.66a.06.06 0 0 0-.03-.03ZM8.02 15.33c-1.18 0-2.16-1.09-2.16-2.42s.96-2.42 2.16-2.42c1.21 0 2.18 1.1 2.16 2.42 0 1.33-.96 2.42-2.16 2.42Zm7.97 0c-1.18 0-2.15-1.09-2.15-2.42s.95-2.42 2.15-2.42c1.21 0 2.18 1.1 2.16 2.42 0 1.33-.95 2.42-2.16 2.42Z" />
    </svg>
  );
}

function XIcon() {
  // The app sidebar's X icon (frontend/src/assets/TwitterX.svg).
  return (
    <svg viewBox="0 0 18 18" fill="currentColor" aria-hidden="true" width="16" height="16">
      <path d="M14.175 0.843262H16.9354L10.9054 7.75269L18 17.1564H12.4457L8.09229 11.4543L3.11657 17.1564H0.353571L6.80271 9.76355L0 0.844547H5.69571L9.62486 6.05555L14.175 0.843262ZM13.2043 15.5004H14.7343L4.86 2.41312H3.21943L13.2043 15.5004Z" />
    </svg>
  );
}

function DocsGPTMark() {
  // The DocsGPT mark, the "D" with its tail (frontend/src/assets/logo-b.svg).
  return (
    <svg viewBox="0 0 233.35 169.38" fill="currentColor" aria-hidden="true" width="20" height="20">
      <path d="M226.85,50.84c-4.34-10.28-10.44-19.23-18.31-26.86-7.87-7.63-17.19-13.53-27.95-17.71-10.76-4.18-22.41-6.26-34.94-6.26h-66.02v140.35c-7.6.66-15.04.42-22.33-.75-11.32-1.82-21.64-5.63-30.94-11.42-9.3-5.79-17.17-13.29-23.6-22.5-.82-1.17-1.61-2.37-2.37-3.59h-.4c1.08,5.74,2.73,11.25,4.93,16.51,4.34,10.36,10.44,19.36,18.31,26.99,7.87,7.63,17.15,13.53,27.83,17.71,8.93,3.49,18.46,5.52,28.56,6.09h0s22.41,0,22.41,0h44.09c12.37,0,23.89-2.09,34.57-6.26,10.68-4.17,19.96-10.08,27.83-17.71,7.87-7.63,13.97-16.62,18.31-26.99,4.34-10.36,6.51-21.64,6.51-33.85s-2.17-23.45-6.51-33.73ZM193,113.84c-4.58,8.43-11,14.94-19.28,19.52-8.27,4.58-17.79,6.87-28.55,6.87h-32.77V29.15h32.77c10.76,0,20.24,2.33,28.43,6.99,8.19,4.66,14.61,11.08,19.28,19.28,4.66,8.19,6.99,17.83,6.99,28.91s-2.29,21.08-6.87,29.52Z" />
      <path d="M19.41,117.55c.49.42,1.27.42,1.97,0h0c.7-.43,1.19-1.21,1.22-1.97l.37-7.84c.05-1.03-.73-1.68-1.74-1.47l-3.36.72-4.21.9c-.73.16-1.42.75-1.74,1.5v.02c-.33.75-.21,1.52.28,1.94l7.21,6.21Z" />
      <path d="M28.73,123.56l11.41,5.35c.78.37,1.8,0,2.6-.9.8-.92,1.2-2.22,1.02-3.29l-1.88-11.08c-.25-1.45-1.47-2.01-2.74-1.25l-4.23,2.53-5.29,3.17c-.92.55-1.65,1.68-1.84,2.87v.03c-.2,1.19.18,2.21.96,2.57Z" />
      <path d="M50.47,130.26c.28,1.59,1.21,2.71,2.36,2.83l16.8,1.72c1.15.12,2.29-.79,2.88-2.29h0c.6-1.52.54-3.34-.16-4.62l-7.28-13.18c-.95-1.72-2.75-1.89-4.02-.37l-4.23,5.07-5.29,6.35c-.92,1.11-1.34,2.86-1.06,4.45v.04Z" />
    </svg>
  );
}

const brand = (
  <div className="brand">
    <FullLogo className="brand-logo" />
    <span className="brand-divider" aria-hidden="true" />
    <span className="brand-label">Docs</span>
  </div>
);

/**
 * The docs chrome around a page: the sidebar built from `tree`, the brand,
 * search and the links to the website, X, Discord and GitHub.
 *
 * @param {{tree: import('fumadocs-core/page-tree').Root, children: import('react').ReactNode}} props The page
 *   tree to show and the page.
 * @returns {import('react').JSX.Element} The layout.
 */
export function DocsShell({ tree, children }) {
  return (
    <DocsLayout
      tree={tree}
      nav={{ title: brand, url: '/' }}
      githubUrl={github}
      // Fumadocs adds the GitHub icon after these.
      links={[
        {
          type: 'icon',
          label: 'DocsGPT website',
          text: 'DocsGPT',
          icon: <DocsGPTMark />,
          url: landing,
          external: true,
        },
        {
          type: 'icon',
          label: 'DocsGPT on X',
          text: 'X',
          icon: <XIcon />,
          url: 'https://x.com/docsgptai',
          external: true,
        },
        {
          type: 'icon',
          label: 'Discord',
          text: 'Discord',
          icon: <DiscordIcon />,
          url: 'https://discord.gg/vN7YFfdMpj',
          external: true,
        },
      ]}
    >
      {children}
    </DocsLayout>
  );
}
