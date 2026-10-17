import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ConfigFields from './ConfigFields';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConfigFields secrets', () => {
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

  const render = async (hasEncryptedCredentials: boolean) => {
    await act(async () => {
      root.render(
        <ConfigFields
          configRequirements={{
            api_key: {
              type: 'string',
              label: 'API key',
              description: 'Your provider key',
              secret: true,
            },
          }}
          values={{}}
          onChange={() => undefined}
          isEditing
          hasEncryptedCredentials={hasEncryptedCredentials}
        />,
      );
    });
  };

  it('a saved secret stays empty, with the saved state as the hint', async () => {
    await render(true);
    const input = container.querySelector('input');
    expect(input?.type).toBe('password');
    expect(input?.value).toBe('');
    expect(input?.placeholder).not.toContain('•');
    expect(container.textContent).toContain('common.savedSecretHint');
  });

  it('an unsaved secret has no saved hint', async () => {
    await render(false);
    expect(container.textContent).not.toContain('common.savedSecretHint');
    expect(container.querySelector('input')?.placeholder).toBe(
      'Your provider key',
    );
  });
});
