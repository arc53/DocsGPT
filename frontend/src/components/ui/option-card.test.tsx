import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { OptionCard } from './option-card';

describe('OptionCard', () => {
  it('renders a whole-card button with icon and title', () => {
    const html = renderToStaticMarkup(
      <OptionCard icon={<svg />} title="Crawler" />,
    );
    expect(html).toMatch(/^<button/);
    expect(html).toContain('Crawler');
    expect(html).toContain('cursor-pointer');
    expect(html).toContain('data-slot="option-card-icon"');
  });

  it('omits the description line when none is given', () => {
    const html = renderToStaticMarkup(
      <OptionCard icon={<svg />} title="GitHub" />,
    );
    expect(html).not.toContain('data-slot="card-description"');
  });

  it('marks the selected tile and fills its icon', () => {
    const html = renderToStaticMarkup(
      <OptionCard
        icon={<svg />}
        title="Classic Agent"
        description="One model, tools and sources."
        selected
      />,
    );
    expect(html).toContain('data-selected="true"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain('bg-primary text-primary-foreground');
    expect(html).toContain('One model, tools and sources.');
  });

  it('is a plain button when it is not part of a single-select picker', () => {
    const html = renderToStaticMarkup(
      <OptionCard icon={<svg />} title="Upload File" />,
    );
    expect(html).not.toContain('role="radio"');
    expect(html).not.toContain('aria-checked');
  });

  it('is an unchecked radio when selected={false} is passed', () => {
    const html = renderToStaticMarkup(
      <OptionCard icon={<svg />} title="Workflow Agent" selected={false} />,
    );
    expect(html).toContain('role="radio"');
    expect(html).toContain('aria-checked="false"');
  });
});
