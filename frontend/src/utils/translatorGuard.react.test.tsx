import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ErrorBoundary from '../components/ErrorBoundary';
import { installTranslatorGuard } from './translatorGuard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Chrome Translate: every text node becomes a <font> holding the translation.
function translatePage(root: Node) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  while (walker.nextNode()) texts.push(walker.currentNode as Text);
  for (const text of texts) {
    const font = document.createElement('font');
    font.textContent = `[es] ${text.data}`;
    text.parentNode!.replaceChild(font, text);
  }
}

let setStep: (step: number) => void = () => undefined;

// Step 0 → 1 inserts before a translated text node; 1 → 2 removes one.
function Answer() {
  const [step, set] = useState(0);
  setStep = set;
  return (
    <p>
      {step >= 1 && <b>new</b>}
      {step < 2 && 'Hello'}
      <span>tail</span>
    </p>
  );
}

describe('a translated page under React', () => {
  let container: HTMLDivElement;
  let root: Root;
  let uninstall: () => void = () => undefined;
  const errors = vi.spyOn(console, 'error').mockImplementation(() => {});

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    errors.mockClear();
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    uninstall();
  });

  const renderTranslated = () => {
    act(() => {
      root.render(
        <ErrorBoundary>
          <Answer />
        </ErrorBoundary>,
      );
    });
    translatePage(container);
  };

  it('falls back to the error screen without the guard', () => {
    renderTranslated();
    act(() => setStep(1));
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    expect(String(errors.mock.calls[0]?.[1])).toContain('insertBefore');
  });

  it('keeps rendering with the guard', () => {
    uninstall = installTranslatorGuard(() => undefined);
    renderTranslated();
    act(() => setStep(1));
    act(() => setStep(2));
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('span')?.textContent).toBe('[es] tail');
    expect(errors).not.toHaveBeenCalled();
  });
});
