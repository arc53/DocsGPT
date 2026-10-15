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

  it('shows how many tools are on beside the Tools label', () => {
    const render = (selectedIds: string[]) =>
      renderToStaticMarkup(
        <ToolsTrigger
          open={false}
          onOpenChange={noop}
          items={[]}
          selectedIds={selectedIds}
          onToggle={noop}
          loading={false}
          onAddTool={noop}
        />,
      );
    const badge = (html: string) =>
      html.match(/<span[^>]*data-slot="badge"[^>]*>([^<]*)<\/span>/);

    const none = render([]);
    expect(badge(none)).toBeNull();
    expect(none).not.toContain('aria-label');

    const three = render(['a', 'b', 'c']);
    expect(badge(three)?.[1]).toBe('3');
    expect(badge(three)?.[0]).toContain('aria-hidden="true"');
    expect(three).toContain('aria-label="settings.tools.triggerLabel"');
  });
});
