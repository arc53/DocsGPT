import type { TFunction } from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';

import { SectionHeader } from '../components/ui/section-header';
import { toolGroupTitle } from './toolGroupTitle';

vi.mock('../connectors/ConnectorIcon', () => ({
  default: () => <svg data-testid="icon" />,
}));

const t = ((key: string) => key) as unknown as TFunction;

describe('toolGroupTitle', () => {
  it("keeps a service heading's count on the title's line", () => {
    const html = renderToStaticMarkup(
      <SectionHeader
        size="sm"
        title={toolGroupTitle(t, {
          kind: 'service',
          service: { key: 'telegram', name: 'Telegram', icon: 'telegram' },
        } as never)}
        count={1}
      />,
    );
    const host = document.createElement('div');
    host.innerHTML = html;
    const title = host.querySelector('h2 > span')!;
    // A block-level flex row would push the count under the name, and the
    // icon's baseline would drop it below the name's.
    expect(title.className).toContain('inline-flex');
    expect(title.className).not.toMatch(/(^|\s)flex(\s|$)/);
    expect(title.className).toContain('align-top');
  });
});
