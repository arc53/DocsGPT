import { beforeAll, describe, expect, it } from 'vitest';

import type { i18n as I18n } from 'i18next';

// Old builds stored the string "undefined" as the language; detection must
// skip it and fall through to the browser languages.
let i18n: I18n;

beforeAll(async () => {
  localStorage.setItem('docsgpt-locale', 'undefined');
  Object.defineProperty(navigator, 'languages', {
    value: ['ru-RU', 'en-US'],
    configurable: true,
  });
  i18n = (await import('./i18n')).default;
});

describe('i18n language detection', () => {
  it('skips a stored "undefined" and reduces the browser region', () => {
    expect(i18n.language).toBe('ru');
    expect(localStorage.getItem('docsgpt-locale')).toBe('ru');
  });

  it('keeps the app codes that are not BCP 47 tags', async () => {
    await i18n.changeLanguage('zhTW');
    expect(i18n.language).toBe('zhTW');
    await i18n.changeLanguage('jp');
    expect(i18n.language).toBe('jp');
  });
});
