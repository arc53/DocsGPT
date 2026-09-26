import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import PageToolbar from './PageToolbar';

describe('PageToolbar', () => {
  it('stacks intro, the search/action row and an opt-in rule', () => {
    const html = renderToStaticMarkup(
      <PageToolbar
        intro="Manage tools"
        search={<input />}
        action={<button type="button">Add Tool</button>}
        divider
      />,
    );
    expect(html).toContain('text-muted-foreground mb-5 text-sm leading-6');
    expect(html).toContain(
      'mb-6 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between',
    );
    expect(html).toContain('w-full max-w-md');
    expect(html).toContain('data-slot="separator"');
    expect(html).toContain('mb-8');
  });

  it('puts the intro in the left slot when there is no search', () => {
    const html = renderToStaticMarkup(
      <PageToolbar
        intro="Tokens"
        action={<button type="button">Create</button>}
      />,
    );
    expect(html).toContain('max-w-2xl');
    expect(html).not.toContain('data-slot="separator"');
  });

  it('renders notices between the row and the rule', () => {
    const html = renderToStaticMarkup(
      <PageToolbar intro="x" action={<span />} divider>
        <p>limit reached</p>
      </PageToolbar>,
    );
    expect(html.indexOf('limit reached')).toBeLessThan(
      html.indexOf('data-slot="separator"'),
    );
  });
});
