import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import type { Agent, ResourceSponsor } from '../types';
import SponsoredResourcesNotice from './SponsoredResourcesNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const baseAgent: Agent = {
  name: 'A',
  description: 'd',
  image: '',
  source: '',
  chunks: '6',
  retriever: '',
  prompt_id: 'default',
  tools: [],
  agent_type: 'classic',
  status: 'published',
};

const sponsor = (over: Partial<ResourceSponsor>): ResourceSponsor => ({
  type: 'tool',
  id: 't1',
  user_id: 'bob',
  label: 'bob@example.com',
  active: true,
  ...over,
});

describe('SponsoredResourcesNotice', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    agent: Agent,
    takeovers: string[] = [],
    onToggleTakeover = vi.fn(),
  ) => {
    await act(async () => {
      root.render(
        <SponsoredResourcesNotice
          agent={agent}
          resolveName={(s) => `name-${s.id}`}
          takeovers={takeovers}
          onToggleTakeover={onToggleTakeover}
        />,
      );
    });
    return onToggleTakeover;
  };

  const buttons = () => Array.from(container.querySelectorAll('button'));

  const alerts = () =>
    Array.from(container.querySelectorAll('[data-slot="alert"]'));

  it('renders nothing for the owner with no sponsored items', async () => {
    await render(baseAgent);
    expect(container.innerHTML).toBe('');
  });

  it('tells an editor their own items run with their access', async () => {
    await render({ ...baseAgent, access: 'editor', allowed_actions: ['edit'] });
    expect(alerts()).toHaveLength(1);
    expect(container.textContent).toContain('agents.form.sponsors.attachNote');
    expect(container.textContent).not.toContain('publicLinkNote');
  });

  it('adds the public-link warning when the agent has a link', async () => {
    await render({
      ...baseAgent,
      shared: true,
      access: 'editor',
      allowed_actions: ['edit'],
    });
    expect(container.textContent).toContain(
      'agents.form.sponsors.publicLinkNote',
    );
  });

  it('does not show the attach note to a viewer', async () => {
    await render({ ...baseAgent, access: 'viewer', allowed_actions: ['use'] });
    expect(container.innerHTML).toBe('');
  });

  it('joins names for the app language and does not escape them', async () => {
    await i18n.use(initReactI18next).init({
      lng: 'jp',
      resources: {
        jp: {
          translation: {
            agents: {
              form: { sponsors: { addedBy: '{{person}}: {{names}}' } },
            },
          },
        },
      },
    });
    try {
      await render({
        ...baseAgent,
        resource_sponsors: [
          sponsor({ id: 'docs/a' }),
          sponsor({ id: 'docs/b' }),
        ],
      });
      const expected = new Intl.ListFormat('ja', {
        type: 'conjunction',
      }).format(['name-docs/a', 'name-docs/b']);
      expect(container.textContent).toBe(`bob@example.com: ${expected}`);
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('splits running and no-longer-running items', async () => {
    await render({
      ...baseAgent,
      resource_sponsors: [
        sponsor({ id: 't1' }),
        sponsor({ id: 's1', type: 'source', active: false }),
      ],
    });
    const [running, stopped] = alerts();
    expect(running.getAttribute('role')).toBe('note');
    expect(running.textContent).toContain('agents.form.sponsors.addedBy');
    expect(stopped.getAttribute('data-variant')).toBe('warning');
    expect(stopped.textContent).toContain('agents.form.sponsors.unavailable');
  });

  it('says why each item stopped', async () => {
    await render({
      ...baseAgent,
      resource_sponsors: [
        sponsor({
          id: 't1',
          active: false,
          state: 'inactive',
          reason: 'sponsor_cannot_edit_agent',
        }),
        sponsor({
          id: 's1',
          type: 'source',
          active: false,
          state: 'inactive',
          reason: 'sponsor_cannot_edit_resource',
        }),
      ],
    });
    const text = container.textContent ?? '';
    expect(text).toContain('agents.form.sponsors.stoppedCannotEditAgent');
    expect(text).toContain('agents.form.sponsors.stoppedCannotEditItem');
    expect(text).not.toContain('agents.form.sponsors.unavailable');
  });

  it('offers a take-over only for items the reader may confirm', async () => {
    const toggle = await render({
      ...baseAgent,
      access: 'editor',
      allowed_actions: ['edit'],
      resource_sponsors: [
        sponsor({ key: 'tool:t1', id: 't1', active: false, can_confirm: true }),
        sponsor({
          key: 'tool:t2',
          id: 't2',
          active: false,
          can_confirm: false,
        }),
      ],
    });
    const takeOver = buttons().filter((b) =>
      b.textContent?.includes('agents.form.sponsors.takeOver'),
    );
    expect(takeOver).toHaveLength(1);
    await act(async () => takeOver[0].click());
    expect(toggle).toHaveBeenCalledWith('tool:t1');
  });

  it('shows a pending take-over with an undo', async () => {
    const toggle = await render(
      {
        ...baseAgent,
        access: 'editor',
        allowed_actions: ['edit'],
        resource_sponsors: [
          sponsor({
            key: 'tool:t1',
            id: 't1',
            active: false,
            can_confirm: true,
          }),
        ],
      },
      ['tool:t1'],
    );
    expect(container.textContent).toContain(
      'agents.form.sponsors.takeOverPending',
    );
    const undo = buttons().find((b) =>
      b.textContent?.includes('agents.form.sponsors.undoTakeOver'),
    )!;
    await act(async () => undo.click());
    expect(toggle).toHaveBeenCalledWith('tool:t1');
  });
});
