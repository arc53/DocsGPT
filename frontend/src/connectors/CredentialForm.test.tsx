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
});
