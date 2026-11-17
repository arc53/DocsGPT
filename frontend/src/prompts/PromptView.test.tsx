import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      Promise.resolve({ json: () => Promise.resolve({ success: false }) }),
  },
}));

import { PromptView, type PromptViewProps } from './PromptView';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('PromptView', () => {
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

  const render = (props: Partial<PromptViewProps> = {}) =>
    act(async () => {
      root.render(
        <PromptView
          parent={{ label: 'Prompts', onClick: () => undefined }}
          label="Support"
          idPrefix="edit"
          name="Support"
          setName={() => undefined}
          content="Be brief."
          setContent={() => undefined}
          {...props}
        />,
      );
    });

  it('leads with the crumb row: the trail, the buttons, then the ⋯', async () => {
    const back = vi.fn();
    await render({
      parent: { label: 'Prompts', onClick: back },
      actions: <button type="button">Save</button>,
      menu: <button type="button">More</button>,
    });
    const row = container.querySelector(
      '[data-slot="breadcrumb"]',
    )!.parentElement!;
    expect(row.className).toContain('min-h-9.5');
    expect(
      Array.from(row.querySelectorAll('button')).map((b) => b.textContent),
    ).toEqual(['Prompts', 'Save', 'More']);
    expect(row.textContent).toContain('Support');
    await act(async () => row.querySelector('button')!.click());
    expect(back).toHaveBeenCalled();
  });

  it('puts the byline under the row and the editor on the background', async () => {
    await render({ byline: 'Used by 3 agents' });
    const byline = container.querySelector('p')!;
    expect(byline.textContent).toBe('Used by 3 agents');
    expect(byline.className).toContain('text-muted-foreground');
    expect(
      container.querySelector('[data-slot="form-field-label"]')!.className,
    ).toContain('bg-background');
  });

  it('holds placeholders while the text loads', async () => {
    await render({ loading: true });
    expect(
      container.querySelector('[data-slot="prompt-view-loading"]'),
    ).not.toBeNull();
    expect(container.querySelector('textarea')).toBeNull();
  });

  it('shows a failed load as an error with Try again', async () => {
    const onRetry = vi.fn();
    await render({ onRetry });
    expect(container.textContent).toContain('settings.prompts.loadPromptError');
    expect(container.querySelector('textarea')).toBeNull();
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(onRetry).toHaveBeenCalled();
  });
});
