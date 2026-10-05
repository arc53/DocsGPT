import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import SkeletonLoader from './SkeletonLoader';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/hooks', () => ({
  useMediaQuery: () => ({ isDesktop: true }),
}));

describe('SkeletonLoader analysis', () => {
  const html = renderToStaticMarkup(<SkeletonLoader component="analysis" />);

  it('renders chart-shaped Skeleton bars with no pulsing wrapper', () => {
    expect(html).toContain('flex h-full flex-col justify-end gap-3');
    expect(html).toContain('grid grid-cols-8 items-end gap-3');
    // Eight chart bars plus the x-axis bar, all Skeletons.
    expect(html.match(/data-slot="skeleton"/g)).toHaveLength(9);
    expect(html).not.toContain('bg-card');
    expect(html).not.toContain('rounded-3xl');
    expect(html).not.toContain('p-6');
    // Only the Skeleton bars pulse.
    expect(html.match(/animate-pulse/g)).toHaveLength(9);
  });

  it('fits the 245px chart box: the tallest bar is h-44', () => {
    expect(html).toContain('h-44');
    expect(html).not.toMatch(/\bh-(48|52|56|60|64|72|80|96)\b/);
  });

  it('keeps the loading status for screen readers', () => {
    expect(html).toContain('role="status"');
  });
});

describe('SkeletonLoader logs', () => {
  const html = renderToStaticMarkup(<SkeletonLoader component="logs" />);

  it('renders eight rows that never take a hover fill', () => {
    expect(html.match(/flex w-full items-start p-2/g)).toHaveLength(8);
    expect(html).not.toContain('hover:');
  });
});
