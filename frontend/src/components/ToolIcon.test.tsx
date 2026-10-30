import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import ToolIcon from './ToolIcon';

const rawIcons = import.meta.glob('../assets/toolIcons/tool_*.svg', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Multi-colour brand marks: the only icons that keep their own colours. */
const BRAND_MARKS = ['brave', 'duckduckgo', 'ntfy', 'postgres', 'telegram'];

describe('ToolIcon', () => {
  it.each(['check_job', 'monitor', 'scheduler', 'code_executor', 'memory'])(
    'draws an icon for the built-in %s tool',
    (name) => {
      expect(renderToStaticMarkup(<ToolIcon name={name} />)).toContain('<svg');
    },
  );

  it('draws the monitor with the same radar as the watching mark', () => {
    expect(renderToStaticMarkup(<ToolIcon name="monitor" />)).toContain(
      'lucide-radar',
    );
  });

  it('draws nothing for a tool it has no icon for', () => {
    expect(renderToStaticMarkup(<ToolIcon name="no_such_tool" />)).toBe('');
  });

  it('labels the icon only when asked', () => {
    expect(
      renderToStaticMarkup(<ToolIcon name="check_job" title="Check Job" />),
    ).toContain('aria-label="Check Job"');
    expect(renderToStaticMarkup(<ToolIcon name="check_job" />)).toContain(
      'aria-hidden="true"',
    );
  });

  it.each(
    Object.entries(rawIcons)
      .map(([path, svg]) => [path.match(/tool_(.+)\.svg$/)![1], svg] as const)
      .filter(([name]) => !BRAND_MARKS.includes(name)),
  )('draws the %s icon in currentColor so it follows the theme', (_, svg) => {
    const paints = Array.from(
      svg.matchAll(/(?:fill|stroke)\s*[:=]\s*["']?\s*([^"';\s>)]+)/gi),
      (match) => match[1],
    );
    expect(
      paints.filter((paint) => !/^(none|currentColor)$/i.test(paint)),
    ).toEqual([]);
  });
});
