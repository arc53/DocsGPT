import { DocsLayout } from 'fumadocs-ui/layouts/docs';

import { FullLogo } from './FullLogo';

const github = 'https://github.com/arc53/DocsGPT';

function DiscordIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" width="20" height="20">
      <path d="M20.32 4.37a19.8 19.8 0 0 0-4.89-1.52.07.07 0 0 0-.08.04c-.21.38-.44.87-.6 1.25a18.27 18.27 0 0 0-5.49 0 12.64 12.64 0 0 0-.62-1.25.08.08 0 0 0-.08-.04 19.74 19.74 0 0 0-4.89 1.52.07.07 0 0 0-.03.03C.53 9.05-.32 13.58.1 18.06a.08.08 0 0 0 .03.06 19.9 19.9 0 0 0 5.99 3.03.08.08 0 0 0 .08-.03c.46-.63.87-1.3 1.23-1.99a.08.08 0 0 0-.04-.11 13.1 13.1 0 0 1-1.87-.89.08.08 0 0 1-.01-.13l.37-.29a.07.07 0 0 1 .08-.01c3.93 1.79 8.18 1.79 12.06 0a.07.07 0 0 1 .08.01l.37.29a.08.08 0 0 1-.01.13c-.6.35-1.22.65-1.87.89a.08.08 0 0 0-.04.11c.36.7.77 1.36 1.22 1.99a.08.08 0 0 0 .08.03 19.84 19.84 0 0 0 6-3.03.08.08 0 0 0 .03-.05c.5-5.18-.84-9.67-3.55-13.66a.06.06 0 0 0-.03-.03ZM8.02 15.33c-1.18 0-2.16-1.09-2.16-2.42s.96-2.42 2.16-2.42c1.21 0 2.18 1.1 2.16 2.42 0 1.33-.96 2.42-2.16 2.42Zm7.97 0c-1.18 0-2.15-1.09-2.15-2.42s.95-2.42 2.15-2.42c1.21 0 2.18 1.1 2.16 2.42 0 1.33-.95 2.42-2.16 2.42Z" />
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
 * search and the GitHub and Discord links.
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
      links={[
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
