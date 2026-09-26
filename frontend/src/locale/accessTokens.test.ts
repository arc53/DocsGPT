import { describe, expect, it } from 'vitest';

import de from './de.json';
import en from './en.json';
import es from './es.json';
import jp from './jp.json';
import ru from './ru.json';
import zhTW from './zh-TW.json';
import zh from './zh.json';

type Tree = { [key: string]: string | Tree };

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

// Plural categories differ per language (ru adds few/many), so compare the
// keys with the suffix stripped.
const flatten = (tree: Tree, prefix = ''): string[] =>
  Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [prefix + key.replace(PLURAL_SUFFIX, '')]
      : flatten(value, `${prefix}${key}.`),
  );

const keysOf = (locale: { settings: object }): string[] => {
  const block = (locale.settings as Tree).accessTokens as Tree;
  return Array.from(new Set(flatten(block))).sort();
};

const LOCALES = { es, de, jp, ru, zh, zhTW };

describe('settings.accessTokens locale block', () => {
  it.each(Object.entries(LOCALES))(
    '%s has the same keys as en',
    (_name, locale) => {
      expect(keysOf(locale)).toEqual(keysOf(en));
    },
  );

  it.each(Object.entries(LOCALES))(
    '%s is translated, not an English copy',
    (_name, locale) => {
      const block = (locale.settings as Tree).accessTokens as Tree;
      const source = (en.settings as Tree).accessTokens as Tree;
      expect(block.label).not.toBe(source.label);
      expect((block.created as Tree).warning).not.toBe(
        (source.created as Tree).warning,
      );
    },
  );
});
