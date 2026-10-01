import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mocks = vi.hoisted(() => ({
  shareAgent: vi.fn(),
  getAgentWebhook: vi.fn(),
  regenerateAgentKey: vi.fn(),
}));

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({ preference: { token: null } }),
}));

vi.mock('../api/services/userService', () => ({ default: mocks }));
// Tested on its own; it needs the store and the tool list. Here it only has
// to show up (or not).
vi.mock('../agents/ApiWriteAllowlist', () => ({
  default: ({ defaultOpen }: { defaultOpen?: boolean }) => (
    <div data-testid="api-write-allowlist" data-open={String(!!defaultOpen)} />
  ),
}));

// A light stand-in for the promise-aware confirm: a resolved submit closes
// it, a rejected one keeps it open with `error`.
vi.mock('./ConfirmationModal', async () => {
  const { useState } = await import('react');
  return {
    default: function MockConfirm({
      modalState,
      setModalState,
      handleSubmit,
      error,
    }: {
      modalState: string;
      setModalState: (s: string) => void;
      handleSubmit: () => unknown;
      error?: string;
    }) {
      const [failed, setFailed] = useState(false);
      if (modalState !== 'ACTIVE') return null;
      const submit = () => {
        const result = handleSubmit();
        if (result instanceof Promise) {
          result.then(
            () => setModalState('INACTIVE'),
            () => setFailed(true),
          );
        } else setModalState('INACTIVE');
      };
      return (
        <div data-testid="confirm">
          {failed && <p data-testid="confirm-error">{error}</p>}
          <button type="button" data-testid="confirm-key" onClick={submit} />
        </div>
      );
    },
  };
});

import type { Agent } from '../agents/types';
import AgentDetailsModal from './AgentDetailsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const respond = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

describe('AgentDetailsModal', () => {
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
    Object.values(mocks).forEach((m) => m.mockReset());
    document.body.innerHTML = '';
  });

  const render = async (agent: Partial<Agent>, openApiWrites?: boolean) => {
    await act(async () => {
      root.render(
        <AgentDetailsModal
          agent={{ id: 'a1', name: 'Bot', ...agent } as Agent}
          mode="edit"
          modalState="ACTIVE"
          setModalState={() => undefined}
          openApiWrites={openApiWrites}
        />,
      );
    });
  };

  // The three sections each have a Generate button until they hold a value.
  const generateButtons = () =>
    Array.from(document.querySelectorAll('button')).filter(
      (b) => b.textContent === 'modals.agentDetails.generate',
    );

  it('generates a missing API key through the reset confirmation', async () => {
    mocks.regenerateAgentKey.mockReturnValue(respond({ key: 'new-key' }));
    await render({ status: 'published' });
    const [, apiKey] = generateButtons();
    await act(async () => apiKey.click());
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[data-testid="confirm-key"]')!
        .click(),
    );
    expect(mocks.regenerateAgentKey).toHaveBeenCalledWith('a1', null);
    expect(document.body.textContent).toContain('new-key');
  });

  it('asks a draft to publish first instead of offering a key', async () => {
    await render({ status: 'draft' });
    expect(generateButtons()).toHaveLength(2);
    expect(document.body.textContent).toContain(
      'modals.agentDetails.apiKeyAfterPublish',
    );
  });

  // The allowlist acts on the owner's connected accounts; the server keeps
  // it unchanged for anyone else, so only the owner sees it.
  describe('API write allowlist', () => {
    const allowlist = () =>
      document.querySelector('[data-testid="api-write-allowlist"]');

    it('shows it to the owner of an agent with a key', async () => {
      await render({ status: 'published', key: 'k-1', access: 'owner' });
      expect(allowlist()).not.toBeNull();
    });

    // It covers the widget and the public link too, not just the key, so
    // it is the modal's last group rather than part of API key.
    it('is its own last group, after the webhook', async () => {
      await render({ status: 'published', key: 'k-1', access: 'owner' });
      const headings = Array.from(document.querySelectorAll('h3'));
      const apiKey = headings.find(
        (h) => h.textContent === 'modals.agentDetails.apiKey',
      )!;
      const webhook = headings.find(
        (h) => h.textContent === 'modals.agentDetails.webhookUrl',
      )!;
      const list = allowlist()!;
      expect(apiKey.closest('div.flex-col')!.contains(list)).toBe(false);
      expect(
        webhook.compareDocumentPosition(list) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(list.parentElement!.lastElementChild).toBe(list);
    });

    it('starts it folded, or open when sent to allow changes', async () => {
      await render({ status: 'published', key: 'k-1', access: 'owner' });
      expect(allowlist()?.getAttribute('data-open')).toBe('false');
      await render({ status: 'published', key: 'k-1', access: 'owner' }, true);
      expect(allowlist()?.getAttribute('data-open')).toBe('true');
    });

    it('hides it from an editor, even with a key', async () => {
      await render({
        status: 'published',
        key: 'k-1',
        access: 'editor',
        allowed_actions: ['view', 'edit', 'manage_access_details'],
      });
      expect(allowlist()).toBeNull();
    });

    it('hides it until the agent has a key', async () => {
      await render({ status: 'published', access: 'owner' });
      expect(allowlist()).toBeNull();
    });
  });

  it('shows a refused public link in an alert', async () => {
    mocks.shareAgent.mockReturnValue(
      respond({ success: false, message: 'Not allowed' }, false),
    );
    await render({ status: 'published' });
    await act(async () => generateButtons()[0].click());
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Not allowed');
    // Destructive Alerts lead with CircleAlert, like every other one.
    expect(alert?.querySelector('svg.lucide-circle-alert')).not.toBeNull();
    expect(alert?.querySelector('svg.lucide-circle-x')).toBeNull();
  });

  it('shows a failed webhook in an alert with a fallback message', async () => {
    mocks.getAgentWebhook.mockReturnValue(respond({}, false));
    await render({ status: 'published' });
    const buttons = generateButtons();
    await act(async () => buttons[buttons.length - 1].click());
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('modals.agentDetails.actionFailed');
  });

  const resetKey = async () => {
    await render({ status: 'published' });
    const [, apiKey] = generateButtons();
    await act(async () => apiKey.click());
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[data-testid="confirm-key"]')!
        .click(),
    );
  };

  it('keeps a refused key reset in the confirm with the server message', async () => {
    mocks.regenerateAgentKey.mockReturnValue(
      respond({ success: false, message: 'Key locked' }, false),
    );
    await resetKey();
    expect(document.querySelector('[data-testid="confirm"]')).not.toBeNull();
    expect(
      document.querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('Key locked');
    // Said once, in the dialog: no Alert in the modal underneath.
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it('falls back to actionFailed when the reset request throws', async () => {
    mocks.regenerateAgentKey.mockImplementation(() =>
      Promise.reject(new Error('x')),
    );
    await resetKey();
    expect(
      document.querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('modals.agentDetails.actionFailed');
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it('closes the confirm once the key is reset', async () => {
    mocks.regenerateAgentKey.mockReturnValue(respond({ key: 'new-key' }));
    await resetKey();
    expect(document.querySelector('[data-testid="confirm"]')).toBeNull();
  });
});
