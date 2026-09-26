import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import SearchInput from './SearchInput';

describe('SearchInput', () => {
  it('is a 38px pill with a search icon and a floating label', () => {
    const html = renderToStaticMarkup(<SearchInput label="Search tools..." />);
    expect(html).toContain('rounded-full');
    expect(html).toContain('h-9.5');
    expect(html).toContain('pl-10');
    expect(html).toContain('<label');
    expect(html).toContain('bg-background');
    expect(html).toContain('lucide-search');
  });

  it('takes a placeholder with an accessible name instead of a label', () => {
    const html = renderToStaticMarkup(
      <SearchInput placeholder="Search logs..." />,
    );
    expect(html).not.toContain('<label');
    expect(html).toContain('aria-label="Search logs..."');
  });
});
