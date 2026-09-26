import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '../ui/tooltip';
import PathHeader from './PathHeader';

const render = (node: React.ReactNode) =>
  renderToStaticMarkup(<TooltipProvider>{node}</TooltipProvider>);

describe('PathHeader', () => {
  it('renders a breadcrumb with clickable parents and a truncating last crumb', () => {
    const html = render(
      <PathHeader
        backLabel="Back"
        onBack={vi.fn()}
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
    expect(html).toContain('aria-label="Back"');
  });

  it('makes the root the current crumb when there are no segments', () => {
    const html = render(
      <PathHeader backLabel="Back" onBack={vi.fn()} root={{ label: 'Docs' }} />,
    );
    expect(html).toContain('data-slot="breadcrumb-page"');
    expect(html).not.toContain('data-slot="breadcrumb-link"');
  });

  it('renders actions on the right', () => {
    const html = render(
      <PathHeader
        backLabel="Back"
        onBack={vi.fn()}
        root={{ label: 'Docs' }}
        actions={<button type="button">Sync</button>}
      />,
    );
    expect(html).toContain('Sync');
  });
});
