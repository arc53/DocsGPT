import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '../ui/tooltip';
import { SourceFolderTrail } from './folderTrail';
import PathHeader from './PathHeader';

const render = (node: React.ReactNode) =>
  renderToStaticMarkup(<TooltipProvider>{node}</TooltipProvider>);

describe('PathHeader', () => {
  it('renders a breadcrumb with clickable parents and a truncating last crumb', () => {
    const html = render(
      <PathHeader
        root={{ label: 'Contracts', onSelect: vi.fn() }}
        segments={[
          { label: 'carriers', onSelect: vi.fn() },
          { label: 'a-very-long-file-name.pdf' },
        ]}
      />,
    );
    expect(html).toContain('data-slot="breadcrumb"');
    expect(html.match(/data-slot="breadcrumb-link"/g)).toHaveLength(2);
    expect(html).toContain('<button type="button"');
    expect(html).toContain('max-w-[32ch]');
    expect(html).toContain('title="a-very-long-file-name.pdf"');
    expect(html).not.toContain('text-primary');
  });

  // Up one level is a crumb, as on the Tools and Teams detail pages
  // (DetailBreadcrumb), never a second back arrow.
  it('has no back button: the crumbs are the way up', () => {
    const html = render(
      <PathHeader
        root={{ label: 'Sources', onSelect: vi.fn() }}
        segments={[{ label: 'Contracts' }]}
      />,
    );
    expect(html).not.toContain('lucide-arrow-left');
    expect(html.match(/<button/g)).toHaveLength(1);
  });

  it('keeps the crumbs on one line: parents truncate with their full name as a title', () => {
    const html = render(
      <PathHeader
        root={{ label: 'Sources', onSelect: vi.fn() }}
        segments={[
          { label: 'Key Accounts & Carrier Network', onSelect: vi.fn() },
          { label: 'carriers' },
        ]}
      />,
    );
    expect(html).toContain('flex-nowrap');
    expect(html).toContain('title="Key Accounts &amp; Carrier Network"');
    expect(html).toMatch(/class="[^"]*truncate[^"]*"[^>]*>Key Accounts/);
  });

  it('makes the root the current crumb when there are no segments', () => {
    const html = render(<PathHeader root={{ label: 'Docs' }} />);
    expect(html).toContain('data-slot="breadcrumb-page"');
    expect(html).not.toContain('data-slot="breadcrumb-link"');
  });

  it('renders actions on the right', () => {
    const html = render(
      <PathHeader
        root={{ label: 'Docs' }}
        actions={<button type="button">Sync</button>}
      />,
    );
    expect(html).toContain('Sync');
  });

  it("draws the source's menu last, after the actions", () => {
    const html = render(
      <PathHeader
        root={{ label: 'Docs' }}
        actions={<button type="button">Sync now</button>}
        menu={<button type="button">menu</button>}
      />,
    );
    expect(html.indexOf('Sync now')).toBeLessThan(html.indexOf('menu'));
  });

  it('draws the menu alone when there are no actions', () => {
    const html = render(
      <PathHeader
        root={{ label: 'Docs' }}
        menu={<button type="button">menu</button>}
      />,
    );
    // The row is drawn for the menu: right-aligned, with only the menu in it.
    expect(html).toMatch(
      /<div class="[^"]*justify-end[^"]*"><button type="button">menu<\/button><\/div>/,
    );
  });

  it('puts the kind badge after the crumbs and the byline under the row', () => {
    const html = render(
      <PathHeader
        root={{ label: 'Wiki' }}
        badge={<span data-testid="badge">Living wiki</span>}
        byline="12 pages · 8,111 tokens"
      />,
    );
    expect(html.indexOf('data-slot="breadcrumb"')).toBeLessThan(
      html.indexOf('data-testid="badge"'),
    );
    expect(html).toContain(
      '<p class="text-muted-foreground text-sm">12 pages · 8,111 tokens</p>',
    );
  });

  it('a lone crumb is the current page and no button', () => {
    const html = render(<PathHeader root={{ label: 'Files' }} />);
    expect(html).not.toContain('<button');
    expect(html).toContain('data-slot="breadcrumb-page"');
  });

  // A source opened inside a Knowledge folder: Knowledge › Carriers › source.
  it('puts the folder trail it was opened in after the root', () => {
    const html = render(
      <SourceFolderTrail.Provider
        value={[{ label: 'Carriers', onSelect: vi.fn() }]}
      >
        <PathHeader
          root={{ label: 'Knowledge', onSelect: vi.fn() }}
          segments={[{ label: 'Rate sheet' }]}
        />
      </SourceFolderTrail.Provider>,
    );
    const labels = [...html.matchAll(/>([^<>]+)<\/(?:button|span)>/g)].map(
      (match) => match[1],
    );
    expect(labels.filter((label) => label.trim())).toEqual([
      'Knowledge',
      'Carriers',
      'Rate sheet',
    ]);
  });

  // An embedded tree's root is the source itself: no folders after it.
  it('leaves the trail out when told to', () => {
    const html = render(
      <SourceFolderTrail.Provider value={[{ label: 'Carriers' }]}>
        <PathHeader root={{ label: 'Rate sheet' }} parents={[]} />
      </SourceFolderTrail.Provider>,
    );
    expect(html).not.toContain('Carriers');
  });
});
