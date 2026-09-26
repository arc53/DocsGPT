import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
  cardVariants,
} from './card';

describe('Card', () => {
  it('is a bordered card surface by default', () => {
    const html = renderToStaticMarkup(<Card>Body</Card>);
    expect(html).toContain('rounded-2xl');
    expect(html).toContain('bg-card');
    expect(html).toContain('p-4');
    expect(html).toContain('data-variant="outline"');
  });

  it('destructive tone is the status soft fill and border on any variant', () => {
    const html = renderToStaticMarkup(
      <Card variant="subtle" tone="destructive">
        Danger
      </Card>,
    );
    expect(html).toContain('border-destructive/50');
    expect(html).toContain('bg-destructive/10');
    expect(html).not.toContain('bg-background');
    expect(html).not.toContain('border-border');
    expect(html).toContain('data-tone="destructive"');
  });

  it('destructive tone turns muted text inside it to foreground', () => {
    const classes = cardVariants({ tone: 'destructive' });
    expect(classes).toContain('[&_.text-muted-foreground]:text-foreground');
  });

  it('CardTitle renders the heading level passed in as', () => {
    const html = renderToStaticMarkup(<CardTitle as="h2">Tools</CardTitle>);
    expect(html).toMatch(/^<h2[^>]*data-slot="card-title"/);
    expect(renderToStaticMarkup(<CardTitle>Tools</CardTitle>)).toMatch(/^<div/);
  });

  it('filled variant drops the border', () => {
    const classes = cardVariants({ variant: 'filled' });
    expect(classes).toContain('bg-muted');
    expect(classes).not.toMatch(/(^|\s)border(\s|$)/);
  });

  it('interactive cards get hover, focus and selected styles', () => {
    const html = renderToStaticMarkup(
      <Card interactive selected asChild>
        <button type="button">Pick me</button>
      </Card>,
    );
    expect(html).toContain('<button');
    expect(html).toContain('cursor-pointer');
    expect(html).toContain('data-selected="true"');
    expect(html).toContain('focus-visible:ring-3');
  });

  it('header places the action in the trailing column', () => {
    const html = renderToStaticMarkup(
      <CardHeader>
        <CardTitle>Arc53</CardTitle>
        <CardAction>menu</CardAction>
      </CardHeader>,
    );
    expect(html).toContain('grid-cols-[1fr_auto]');
    expect(html).toContain('col-start-2');
  });

  it('exposes padding and interactive as data attributes', () => {
    const html = renderToStaticMarkup(
      <Card padding="none" interactive>
        Body
      </Card>,
    );
    expect(html).toContain('data-padding="none"');
    expect(html).toContain('data-interactive="true"');
  });

  it('CardDescription is 14px by default and 12px relaxed at size xs', () => {
    expect(
      renderToStaticMarkup(<CardDescription>d</CardDescription>),
    ).toContain('text-muted-foreground text-sm');
    const xs = renderToStaticMarkup(
      <CardDescription size="xs">d</CardDescription>,
    );
    expect(xs).toContain('text-xs leading-relaxed');
    expect(xs).not.toContain('text-sm');
  });
});
