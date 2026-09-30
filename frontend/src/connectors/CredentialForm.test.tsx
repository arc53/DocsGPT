import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) =>
      opts?.defaultValue ?? key,
  }),
}));

import CredentialForm from './CredentialForm';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('CredentialForm', () => {
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

  it('shows a field hint under the field and links it to the input', async () => {
    await act(async () => {
      root.render(
        <CredentialForm
          connectorKey="telegram"
          idPrefix="connect-telegram"
          fields={[
            { key: 'token', label: 'Bot token', secret: true, required: true },
            {
              key: 'chat_id',
              label: 'Default chat ID',
              secret: false,
              required: false,
              hint: 'Messages go to this chat.',
            },
          ]}
          values={{}}
          onChange={() => undefined}
        />,
      );
    });
    const input = container.querySelector<HTMLInputElement>(
      '#connect-telegram-chat_id',
    )!;
    expect(input.type).toBe('text');
    const hintId = input.getAttribute('aria-describedby')!;
    expect(document.getElementById(hintId)?.textContent).toBe(
      'Messages go to this chat.',
    );
    expect(container.textContent).toContain('Default chat ID');
  });
  it('renders the words in <link> as a link to the hint URL', async () => {
    await act(async () => {
      root.render(
        <CredentialForm
          connectorKey="github"
          idPrefix="connect-github"
          fields={[
            {
              key: 'access_token',
              label: 'Personal access token',
              secret: true,
              required: true,
              hint: 'Fine-grained. <link>Create a token on GitHub</link>',
              hint_url:
                'https://github.com/settings/personal-access-tokens/new',
            },
          ]}
          values={{}}
          onChange={() => undefined}
        />,
      );
    });
    const input = container.querySelector<HTMLInputElement>(
      '#connect-github-access_token',
    )!;
    const hint = document.getElementById(
      input.getAttribute('aria-describedby')!,
    )!;
    expect(hint.textContent).toBe('Fine-grained. Create a token on GitHub');
    const link = hint.querySelector('a')!;
    expect(link.getAttribute('href')).toBe(
      'https://github.com/settings/personal-access-tokens/new',
    );
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.textContent).toBe('Create a token on GitHub');
    // A 12px link in a 12px hint, its icon trailing.
    expect(link.className).toContain('text-xs');
    expect(link.lastElementChild?.tagName.toLowerCase()).toBe('svg');
  });

  it('shows a hint with no URL as plain text', async () => {
    await act(async () => {
      root.render(
        <CredentialForm
          connectorKey="telegram"
          idPrefix="connect-telegram"
          fields={[
            {
              key: 'chat_id',
              label: 'Default chat ID',
              secret: false,
              required: false,
              hint: 'Find it with <link>getUpdates</link>.',
            },
          ]}
          values={{}}
          onChange={() => undefined}
        />,
      );
    });
    expect(container.querySelector('a')).toBeNull();
    expect(container.textContent).toContain('Find it with getUpdates.');
  });
});
