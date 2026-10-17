import { renderToStaticMarkup } from 'react-dom/server';

import AgentPageToolbar from './AgentPageToolbar';

describe('AgentPageToolbar', () => {
  it('puts the agent byline beside the actions and closes with a rule', () => {
    const html = renderToStaticMarkup(
      <AgentPageToolbar
        name="Carrier onboarding FAQ"
        status={<span data-testid="status">Published</span>}
        meta="Last used at 21 Sep"
        actions={<button type="button">Save</button>}
      />,
    );
    expect(html).toContain('data-slot="page-toolbar"');
    expect(html).toContain('Carrier onboarding FAQ');
    expect(html).toContain('data-testid="status"');
    expect(html).toContain('Last used at 21 Sep');
    expect(html).toContain('<button type="button">Save</button>');
    expect(html).toContain('data-slot="separator"');
  });

  // On a phone, a status badge fills the first line: the meta takes a line
  // of its own there, without a dangling separator.
  it('moves the meta to its own line on a phone when there is a status', () => {
    const html = renderToStaticMarkup(
      <AgentPageToolbar
        name="FAQ"
        status={<span>Published</span>}
        meta="Last used"
      />,
    );
    expect(html).toContain(
      '<span aria-hidden="true" class="hidden sm:inline">·</span>',
    );
    expect(html).toContain(
      '<span class="basis-full sm:basis-auto">Last used</span>',
    );
  });

  it('keeps the meta on the name line when there is no status', () => {
    const html = renderToStaticMarkup(
      <AgentPageToolbar name="FAQ" meta="Last used" />,
    );
    expect(html).toContain(
      '<span aria-hidden="true">·</span><span>Last used</span>',
    );
  });

  it('keeps the row at field height when a tab has no actions', () => {
    const html = renderToStaticMarkup(<AgentPageToolbar name="FAQ" />);
    // A 38px spacer stands in for the actions, so the rule lands in the same
    // place on every agent tab.
    expect(html).toContain('h-9.5');
  });

  it('renders notices between the row and the rule', () => {
    const html = renderToStaticMarkup(
      <AgentPageToolbar name="FAQ">
        <p>Save failed</p>
      </AgentPageToolbar>,
    );
    expect(html.indexOf('Save failed')).toBeLessThan(
      html.indexOf('data-slot="separator"'),
    );
  });
});
