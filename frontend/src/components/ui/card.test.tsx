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

  it('rings the whole card while a section-toggle inside it has keyboard focus', () => {
    const classes = cardVariants({ variant: 'subtle' });
    expect(classes).toContain(
      'has-[[data-variant=section-toggle]:focus-visible]:ring-3',
    );
    expect(classes).toContain(
      'has-[[data-variant=section-toggle]:focus-visible]:ring-inset',
    );
  });

  it('destructive tone turns muted text inside it to foreground', () => {
    const classes = cardVariants({ tone: 'destructive' });
    expect(classes).toContain(
      '[&_.text-muted-foreground:not([data-slot=button]:hover)]:text-foreground',
    );
  });

  it('destructive tone leaves a hovered button its own hover colour', () => {
    // The muted-to-foreground rule used to beat a ghost-destructive button's
    // hover:text-destructive on source order (the orphan guardrail Remove).
    const classes = cardVariants({ tone: 'destructive' });
    // A regex, so Tailwind's scanner doesn't emit the old rule from this file.
    expect(classes).not.toMatch(/\[&_\.text-muted-foreground\]:/);
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

  it('interactive cards get hover and focus styles', () => {
    const html = renderToStaticMarkup(
      <Card interactive asChild>
        <button type="button">Pick me</button>
      </Card>,
    );
    expect(html).toContain('<button');
    expect(html).toContain('cursor-pointer');
    expect(html).toContain('focus-visible:ring-3');
    // The selected look belongs to OptionCard, its only user.
    expect(html).not.toContain('data-[selected=true]');
  });

  it('has no selected prop', () => {
    // @ts-expect-error selected moved into OptionCard
    const html = renderToStaticMarkup(<Card selected />);
    expect(html).not.toContain('data-selected');
  });

  it('interactive="within" draws a stretched inner button\'s hover and focus ring', () => {
    const html = renderToStaticMarkup(
      <Card variant="filled" interactive="within">
        <button type="button">Open</button>
      </Card>,
    );
    expect(html).toContain('relative');
    expect(html).toContain('hover:bg-accent');
    expect(html).toContain('has-[&gt;button:focus-visible]:ring-3');
    expect(html).toContain('has-[&gt;button:focus-visible]:ring-ring/50');
    // The card itself is not the target: no pointer, no own focus ring.
    expect(html).not.toContain('cursor-pointer');
    expect(html).toContain('data-interactive="within"');
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

  it('CardTitle titles its string text when it truncates; CardDescription never does', () => {
    expect(
      renderToStaticMarkup(
        <CardTitle className="truncate">Meridian Freight Group</CardTitle>,
      ),
    ).toContain('title="Meridian Freight Group"');
    expect(
      renderToStaticMarkup(
        <CardDescription className="line-clamp-2">
          Carrier contracts
        </CardDescription>,
      ),
    ).not.toContain('title=');
  });

  it('CardTitle adds no title when it does not truncate, or the text is a node', () => {
    expect(renderToStaticMarkup(<CardTitle>Tools</CardTitle>)).not.toContain(
      'title=',
    );
    expect(
      renderToStaticMarkup(
        <CardTitle className="truncate">
          <span>Tools</span>
        </CardTitle>,
      ),
    ).not.toContain(' title=');
    expect(
      renderToStaticMarkup(
        <CardTitle className="truncate" title="Full name">
          Full
        </CardTitle>,
      ),
    ).toContain('title="Full name"');
  });
});
