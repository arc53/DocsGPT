import i18n from 'i18next';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { initReactI18next } from 'react-i18next';

import en from '../locale/en.json';
import { promptCheckText } from './promptCheckText';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('promptCheckText', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeAll(async () => {
    await i18n.use(initReactI18next).init({
      lng: 'en',
      resources: { en: { translation: en } },
    });
  });
  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('says the citation rules are missing without predicting the answers, the variable as code', async () => {
    const text = promptCheckText(i18n.t, { code: 'citations_missing' });
    await act(async () => root.render(<p>{text}</p>));
    expect(container.textContent).toBe(
      "It doesn't use {{ source.citation_rules }}, so DocsGPT's [1], [2] citation rules aren't in the prompt",
    );
    const code = container.querySelector('code')!;
    expect(code.textContent).toBe('{{ source.citation_rules }}');
    expect(code.className).toBe('font-mono');
  });

  it('keeps the line after a sentence that has one', () => {
    expect(
      promptCheckText(i18n.t, { code: 'boundaries_missing', line: 3 }),
    ).toBe(
      'It has no Boundaries section, so the agent may follow instructions hidden in documents or tool results (line 3)',
    );
  });
});
