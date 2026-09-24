import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { Dropzone } from './dropzone';

describe('Dropzone', () => {
  it('renders the default prompt as a dashed card target', () => {
    const html = renderToStaticMarkup(<Dropzone onDrop={vi.fn()} />);
    expect(html).toContain('Click to upload or drag and drop');
    expect(html).toContain('border-dashed');
    expect(html).toContain('data-slot="dropzone"');
    expect(html).toContain('<input');
  });

  it('shows description, error and custom title', () => {
    const html = renderToStaticMarkup(
      <Dropzone
        onDrop={vi.fn()}
        title="Drop your agent"
        description=".yaml or .yml"
        error="Only .yaml files are supported"
      />,
    );
    expect(html).toContain('Drop your agent');
    expect(html).toContain('.yaml or .yml');
    expect(html).toContain('Only .yaml files are supported');
    expect(html).toContain('text-destructive');
  });

  it('marks the disabled and compact states with data attributes', () => {
    const html = renderToStaticMarkup(
      <Dropzone onDrop={vi.fn()} disabled size="compact" />,
    );
    expect(html).toContain('data-disabled="true"');
    expect(html).toContain('data-size="compact"');
  });

  it('never uses raw palette colours', () => {
    const html = renderToStaticMarkup(<Dropzone onDrop={vi.fn()} />);
    expect(html).not.toMatch(/\b(bg|text|border)-(gray|red|green|blue)-\d+/);
  });
});
