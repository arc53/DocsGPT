import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import WebsiteFields from './WebsiteFields';
import { defaultWebsiteDraft, type WebsiteDraft } from './website';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const HINT = 'modals.uploadDoc.website.invalidAddress';

describe('WebsiteFields', () => {
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

  const render = (draft: WebsiteDraft) =>
    act(async () =>
      root.render(
        <WebsiteFields draft={draft} onChange={() => {}} maxPages={100} />,
      ),
    );

  const inputs = () =>
    Array.from(
      container.querySelectorAll<HTMLInputElement>('input[type="url"]'),
    );

  const blur = (input: HTMLInputElement) =>
    act(async () => {
      input.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
      input.dispatchEvent(new FocusEvent('blur'));
    });

  it.each([
    'localhost:3000/docs',
    '192.168.1.10/wiki',
    'intranet/docs',
    'https://user:pass@docs.x.io/a',
  ])('says why %s is refused once the field is left', async (url) => {
    await render({ ...defaultWebsiteDraft(10), urls: [url] });
    // Not while it is being typed.
    expect(container.textContent).not.toContain(HINT);
    await blur(inputs()[0]);

    expect(inputs()[0].getAttribute('aria-invalid')).toBe('true');
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toBe(HINT);
    expect(inputs()[0].getAttribute('aria-describedby')).toContain(alert!.id);
  });

  it('marks only the refused row', async () => {
    await render({
      ...defaultWebsiteDraft(10),
      urls: ['docs.x.io/a', 'localhost/b'],
    });
    for (const input of inputs()) await blur(input);

    const [good, bad] = inputs();
    expect(good.getAttribute('aria-invalid')).not.toBe('true');
    expect(bad.getAttribute('aria-invalid')).toBe('true');
    expect(container.querySelectorAll('[role="alert"]')).toHaveLength(1);
  });

  it('leaves a public address and an empty row unmarked', async () => {
    await render({
      ...defaultWebsiteDraft(10),
      urls: ['docs.x.io:8080/guide', ''],
    });
    for (const input of inputs()) await blur(input);

    expect(container.querySelector('[aria-invalid="true"]')).toBeNull();
    expect(container.textContent).not.toContain(HINT);
  });
});
