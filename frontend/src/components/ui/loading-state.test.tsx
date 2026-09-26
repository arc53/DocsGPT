import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { LoadingState } from './loading-state';

describe('LoadingState', () => {
  it('fills its parent by default with one status ring', () => {
    const html = renderToStaticMarkup(<LoadingState />);
    expect(html).toContain('h-full');
    expect(html).toContain('aria-label="loading"');
    expect(html.match(/role="status"/g)).toHaveLength(1);
  });

  it('uses py-10 for block and h-screen for screen', () => {
    expect(renderToStaticMarkup(<LoadingState fill="block" />)).toContain(
      'py-10',
    );
    expect(renderToStaticMarkup(<LoadingState fill="screen" />)).toContain(
      'h-screen',
    );
  });

  it('shows a caption hidden from screen readers under the ring', () => {
    const html = renderToStaticMarkup(
      <LoadingState fill="block" label="Converting..." />,
    );
    expect(html).toContain('flex-col gap-3');
    expect(html).toContain('aria-label="Converting..."');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('text-muted-foreground text-sm');
  });
});
