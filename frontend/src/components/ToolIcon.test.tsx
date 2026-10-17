import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import ToolIcon from './ToolIcon';

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
});
