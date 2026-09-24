import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from './accordion';

function renderAccordion(): string {
  return renderToStaticMarkup(
    <Accordion type="single" collapsible>
      <AccordionItem value="audit">
        <AccordionTrigger>Recent activity</AccordionTrigger>
        <AccordionContent>Rows</AccordionContent>
      </AccordionItem>
    </Accordion>,
  );
}

/** The class attribute of the element carrying the given data-slot. */
function slotClasses(html: string, slot: string): string {
  const tag = new RegExp(`<[^>]*data-slot="${slot}"[^>]*>`).exec(html)?.[0];
  return /class="([^"]*)"/.exec(tag ?? '')?.[1] ?? '';
}

describe('AccordionTrigger', () => {
  it('carries its own inset and section-heading type', () => {
    const classes = slotClasses(renderAccordion(), 'accordion-trigger');
    expect(classes).toContain('px-4');
    expect(classes).toContain('py-3');
    expect(classes).toContain('text-sm');
    expect(classes).toContain('font-medium');
  });

  it('draws the focus ring inside the item, which clips outside it', () => {
    const classes = slotClasses(renderAccordion(), 'accordion-trigger');
    expect(classes).toContain('focus-visible:ring-3');
    expect(classes).toContain('focus-visible:ring-inset');
    expect(classes).not.toContain('focus-visible:ring-2');
  });

  it('keeps the chevron in muted-foreground in dark mode', () => {
    const html = renderAccordion();
    expect(html).toContain('text-muted-foreground');
    expect(html).not.toContain('dark:invert');
  });
});
