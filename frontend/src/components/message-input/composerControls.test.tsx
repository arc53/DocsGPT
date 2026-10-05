import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import AttachFileButton from './AttachFileButton';
import SourcesTrigger from './SourcesTrigger';
import ToolsTrigger from './ToolsTrigger';

const iconClass = (html: string, icon: string): string => {
  const match = html.match(
    new RegExp(`<svg[^>]*class="([^"]*lucide-${icon}[^"]*)"`),
  );
  return match ? match[1] : '';
};

const noop = () => undefined;

describe('composer controls', () => {
  it('sizes every control icon size-3.5 sm:size-4', () => {
    const cases: Array<[string, string]> = [
      [renderToStaticMarkup(<AttachFileButton onChange={noop} />), 'paperclip'],
      [
        renderToStaticMarkup(
          <ToolsTrigger
            open={false}
            onOpenChange={noop}
            items={[]}
            selectedIds={[]}
            onToggle={noop}
            loading={false}
            onAddTool={noop}
          />,
        ),
        'wrench',
      ],
      [
        renderToStaticMarkup(
          <SourcesTrigger
            open={false}
            onOpenChange={noop}
            items={[]}
            selectedIds={[]}
            onToggle={noop}
            selectedDocs={null}
            onUploadClick={noop}
          />,
        ),
        'database',
      ],
    ];
    for (const [html, icon] of cases) {
      const classes = iconClass(html, icon).split(' ');
      expect(classes, icon).toContain('size-3.5');
      expect(classes, icon).toContain('sm:size-4');
    }
  });
});
