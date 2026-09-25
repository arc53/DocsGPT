import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

describe('Tooltip', () => {
  it('renders its trigger without needing an app-level provider', () => {
    const html = renderToStaticMarkup(
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button">Delete</button>
        </TooltipTrigger>
        <TooltipContent>Delete this source</TooltipContent>
      </Tooltip>,
    );
    expect(html).toContain('data-slot="tooltip-trigger"');
    expect(html).toContain('Delete');
  });
});
