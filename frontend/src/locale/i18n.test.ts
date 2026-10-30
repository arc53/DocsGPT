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

  it('picks Traditional Chinese for a zh-TW browser', async () => {
    await i18n.changeLanguage('zh-TW');
    expect(i18n.language).toBe('zh-TW');
  });

  it('reads the zhTW code older builds stored as zh-TW', () => {
    localStorage.setItem('docsgpt-locale', 'zhTW');
    const detector = i18n.services.languageDetector as {
      detect: () => string[];
    };
    expect(detector.detect()[0]).toBe('zh-TW');
  });

  it('reads Hong Kong, Macau and Hant browsers as Traditional', () => {
    localStorage.removeItem('docsgpt-locale');
    const detector = i18n.services.languageDetector as {
      detect: () => string[];
    };
    for (const browser of ['zh-HK', 'zh-MO', 'zh-Hant', 'zh-Hant-TW']) {
      Object.defineProperty(navigator, 'languages', {
        value: [browser],
        configurable: true,
      });
      expect(detector.detect()[0]).toBe('zh-TW');
    }
  });

  it('counts with the Chinese plural rule, which has no _one', async () => {
    await i18n.changeLanguage('zh-TW');
    expect(
      i18n.t('settings.connectors.parameters.fixedCount', {
        count: 1,
        formatted: '1',
      }),
    ).toBe('已固定 1 個');
  });

  it('picks Japanese for a Japanese browser', async () => {
    await i18n.changeLanguage('ja-JP');
    expect(i18n.language).toBe('ja');
  });

  it('reads the jp code older builds stored as ja', () => {
    localStorage.setItem('docsgpt-locale', 'jp');
    const detector = i18n.services.languageDetector as {
      detect: () => string[];
    };
    expect(detector.detect()[0]).toBe('ja');
  });

  it('counts with the Japanese plural rule, which has no _one', async () => {
    await i18n.changeLanguage('ja');
    expect(
      i18n.t('settings.connectors.parameters.fixedCount', {
        count: 1,
        formatted: '1',
      }),
    ).toBe('1 件固定');
  });

  it('accepts French and reduces a French region to it', async () => {
    await i18n.changeLanguage('fr-CA');
    expect(i18n.language).toBe('fr');
  });
});

describe('html lang', () => {
  it('follows the UI language as a BCP 47 tag', async () => {
    // A page that declares English while showing Spanish invites the
    // browser's translator, whose DOM rewrites crash React.
    await i18n.changeLanguage('de');
    expect(document.documentElement.lang).toBe('de');
    await i18n.changeLanguage('fr');
    expect(document.documentElement.lang).toBe('fr');
    await i18n.changeLanguage('zh-TW');
    expect(document.documentElement.lang).toBe('zh-TW');
    await i18n.changeLanguage('ja');
    expect(document.documentElement.lang).toBe('ja');
  });
});
