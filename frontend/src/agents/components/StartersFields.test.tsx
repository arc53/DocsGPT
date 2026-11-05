import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { number?: number }) =>
      options?.number ? `${key}:${options.number}` : key,
  }),
}));

import StartersFields from './StartersFields';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('StartersFields', () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: string[];

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function Harness({ initial }: { initial: string[] }) {
    const [starters, setStarters] = useState(initial);
    latest = starters;
    return <StartersFields starters={starters} onChange={setStarters} />;
  }

  const render = (initial: string[] = []) =>
    act(() => root.render(<Harness initial={initial} />));
  const inputs = () =>
    Array.from(container.querySelectorAll<HTMLInputElement>('input'));
  const addLink = () =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'agents.form.starters.add',
    );
  const type = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    act(() => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('starts with no fields, only the add link', () => {
    render();
    expect(inputs()).toHaveLength(0);
    expect(addLink()).toBeDefined();
  });

  it('adds a focused field and keeps what is typed', () => {
    render();
    act(() => addLink()!.click());
    expect(inputs()).toHaveLength(1);
    expect(document.activeElement).toBe(inputs()[0]);
    type(inputs()[0], 'What can you help me with?');
    expect(latest).toEqual(['What can you help me with?']);
  });

  it('stops offering more at four', () => {
    render(['One', 'Two', 'Three']);
    act(() => addLink()!.click());
    expect(inputs()).toHaveLength(4);
    expect(addLink()).toBeUndefined();
  });

  it('removes the starter its button names', () => {
    render(['One', 'Two', 'Three']);
    const remove = container.querySelector<HTMLButtonElement>(
      'button[aria-label="agents.form.starters.remove:2"]',
    );
    act(() => remove!.click());
    expect(latest).toEqual(['One', 'Three']);
    expect(inputs().map((input) => input.value)).toEqual(['One', 'Three']);
  });
});
