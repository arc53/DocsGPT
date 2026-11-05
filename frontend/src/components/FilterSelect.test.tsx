import { renderToStaticMarkup } from 'react-dom/server';

import FilterSelect from './FilterSelect';

const VALUES = ['all', 'inUse', 'unused'] as const;
const LABELS = { all: 'Any use', inUse: 'In use', unused: 'Unused' };

const render = (
  value: (typeof VALUES)[number],
  counts: Record<(typeof VALUES)[number], number>,
) =>
  renderToStaticMarkup(
    <FilterSelect
      value={value}
      onValueChange={() => undefined}
      values={VALUES}
      counts={counts}
      labelOf={(v) => LABELS[v]}
      ariaLabel="Filter by use"
    />,
  );

describe('FilterSelect', () => {
  it('shows the default without a count, so it never echoes All', () => {
    const html = render('all', { all: 102, inUse: 14, unused: 88 });
    expect(html).toContain('aria-label="Filter by use"');
    expect(html).toContain('Any use');
    expect(html).not.toContain('102');
  });

  it('shows a picked value with its count', () => {
    const html = render('inUse', { all: 102, inUse: 14, unused: 88 });
    expect(html).toContain('In use');
    expect(html).toContain('>14<');
  });

  it('draws nothing when only the default would be left', () => {
    expect(render('all', { all: 4, inUse: 0, unused: 0 })).toBe('');
  });
});
