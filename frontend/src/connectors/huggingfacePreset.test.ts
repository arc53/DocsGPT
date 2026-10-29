import { describe, expect, it } from 'vitest';

import { connectorIconKey, connectorLocaleKey } from './i18n';

const LOCALES = ['en', 'de', 'es', 'fr', 'jp', 'ru', 'zh', 'zh-TW'];

const localeFiles = import.meta.glob<Record<string, unknown>>(
  '../locale/*.json',
  { eager: true, import: 'default' },
);

const iconFiles = import.meta.glob<string>('../assets/connectors/*.svg', {
  eager: true,
  query: '?raw',
  import: 'default',
});

describe('the Hugging Face connector', () => {
  it('uses the Hub logo rather than the plug fallback', () => {
    expect(connectorIconKey('mcp:huggingface')).toBe('huggingface');
  });

  it('ships the logo asset the card renders', () => {
    const svg = iconFiles['../assets/connectors/huggingface.svg'];
    expect(svg).toBeDefined();
    // Without a viewBox the icon scales to its container and breaks the grid.
    expect(svg).toMatch(/viewBox="/);
  });

  it('reads its description from the locale file', () => {
    expect(connectorLocaleKey('mcp:huggingface')).toBe('mcp_huggingface');
  });

  it('has a description in every locale', () => {
    for (const locale of LOCALES) {
      const messages = localeFiles[`../locale/${locale}.json`] as {
        settings: { connectors: { descriptions: Record<string, string> } };
      };
      expect(
        messages.settings.connectors.descriptions.mcp_huggingface,
        `${locale}.json`,
      ).toBeTruthy();
    }
  });
});
