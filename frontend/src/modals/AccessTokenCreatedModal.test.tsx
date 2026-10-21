import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AccessTokenCreatedModal from './AccessTokenCreatedModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AccessTokenCreatedModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  // V3: the token and both snippets are ui/code-block CopyFields, each with
  // the one icon-only copy button (the token row lost its "Copy" label).
  it('shows the token and snippets as CopyFields with icon-only copy buttons', () => {
    act(() =>
      root.render(
        <AccessTokenCreatedModal
          token="dgpt_pat_7Qm2"
          name="CI"
          onClose={() => {}}
        />,
      ),
    );
    const token = document.querySelector<HTMLElement>(
      '[data-testid="pat-plaintext"]',
    )!;
    expect(token.textContent).toBe('dgpt_pat_7Qm2');
    expect(token.className.split(' ')).toEqual(
      expect.arrayContaining(['py-2', 'select-all', 'wrap-anywhere']),
    );
    const copies = Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        'button[aria-label="conversation.copy"]',
      ),
    );
    expect(copies).toHaveLength(3);
    for (const button of copies) {
      expect(button.dataset.size).toBe('icon-sm');
      expect(button.textContent).not.toContain('conversation.copy');
    }
    const fields = Array.from(document.querySelectorAll('pre'));
    expect(fields).toHaveLength(3);
    for (const field of fields) {
      expect(field.className).not.toContain('leading-relaxed');
      expect(field.className).toContain('select-all');
    }
  });
});

describe('AccessTokenCreatedModal agent tool', () => {
  let container: HTMLDivElement;
  let root: Root;

  const render = (onCreateTool?: () => Promise<void>) =>
    act(() =>
      root.render(
        <AccessTokenCreatedModal
          token="dgpt_pat_7Qm2"
          name="analyst"
          onCreateTool={onCreateTool}
          onClose={() => {}}
        />,
      ),
    );

  const createButton = () =>
    Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
      (button) =>
        button.textContent === 'settings.accessTokens.created.createTool',
    );

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('offers no tool when the token reads nothing agents use', () => {
    render();
    expect(createButton()).toBeUndefined();
  });

  it('offers it as a secondary button and says when the tool is made', async () => {
    const onCreateTool = vi.fn().mockResolvedValue(undefined);
    render(onCreateTool);
    const button = createButton()!;
    expect(button.dataset.variant).toBe('outline');
    await act(async () => button.click());
    expect(onCreateTool).toHaveBeenCalledOnce();
    expect(createButton()).toBeUndefined();
    expect(document.body.textContent).toContain(
      'settings.accessTokens.created.toolCreated',
    );
  });

  it("shows the server's reason when it fails, and lets you retry", async () => {
    const onCreateTool = vi
      .fn()
      .mockRejectedValue(new Error('This token cannot call any endpoint'));
    render(onCreateTool);
    await act(async () => createButton()!.click());
    expect(document.body.textContent).toContain(
      'This token cannot call any endpoint',
    );
    expect(createButton()!.disabled).toBe(false);
  });
});
