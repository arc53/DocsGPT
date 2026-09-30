import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.action === 'string' ? `${key}(${opts.action})` : key,
  }),
}));

import ActionParameters, { ActionParametersToggle } from './ActionParameters';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ActionParametersToggle', () => {
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

  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <ActionParametersToggle
        action="Send message"
        open={open}
        onToggle={() => setOpen(!open)}
      />
    );
  }

  const toggle = () => container.querySelector('button')!;

  it('is named after its action, so each one reads apart', async () => {
    await act(async () => root.render(<Harness />));
    expect(toggle().getAttribute('aria-label')).toBe(
      'settings.connectors.parameters.showFor(Send message)',
    );
    // The visible word stays the same; the name starts with it.
    expect(toggle().textContent).toBe('settings.connectors.parameters.show');
  });

  it('is the link-sm disclosure whose chevron turns when open', async () => {
    await act(async () => root.render(<Harness />));
    expect(toggle().getAttribute('data-variant')).toBe('link');
    expect(toggle().getAttribute('data-size')).toBe('sm');
    const chevron = () => toggle().querySelector('svg')!;
    expect(toggle().firstElementChild).toBe(chevron());
    expect(toggle().getAttribute('aria-expanded')).toBe('false');
    expect(chevron().getAttribute('class')).not.toContain('rotate-90');
    await act(async () => toggle().click());
    expect(toggle().getAttribute('aria-expanded')).toBe('true');
    expect(chevron().getAttribute('class')).toContain('rotate-90');
  });
});

describe('ActionParameters hint', () => {
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

  const param = (fixed: boolean, name: string) => ({
    name,
    description: '',
    type: 'string',
    required: false,
    fixed,
    value: fixed ? 'ops' : null,
  });

  it('explains a fixed value under that value only, with no footnote', async () => {
    await act(async () =>
      root.render(
        <ActionParameters
          parameters={[param(true, 'chat_id'), param(false, 'text')]}
          onSave={async () => true}
        />,
      ),
    );
    const html = container.textContent ?? '';
    expect(html).not.toContain('settings.connectors.parameters.hint');
    const hints = container.querySelectorAll('li');
    expect(hints[0].textContent).toContain(
      'settings.connectors.parameters.fixedHint',
    );
    expect(hints[1].textContent).not.toContain(
      'settings.connectors.parameters.fixedHint',
    );
  });
});
