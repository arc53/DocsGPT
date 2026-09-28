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

const flatten = (tree: Tree, prefix = ''): string[] =>
  Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [prefix + key.replace(PLURAL_SUFFIX, '')]
      : flatten(value, `${prefix}${key}.`),
  );

const values = (tree: Tree): string[] =>
  Object.values(tree).flatMap((value) =>
    typeof value === 'string' ? [value] : values(value),
  );

const block = (locale: object, path: string): Tree =>
  path
    .split('.')
    .reduce<Tree>((node, key) => (node[key] as Tree) ?? {}, locale as Tree);

const keysOf = (locale: object, path: string): string[] =>
  Array.from(new Set(flatten(block(locale, path)))).sort();

const LOCALES = { es, de, jp, ru, zh, zhTW };

// Every block the Connectors work adds strings to.
const BLOCKS = ['settings.connectors'];

describe('connectors locale blocks', () => {
  it.each(Object.entries(LOCALES))(
    '%s has the same connector keys as en',
    (_name, locale) => {
      for (const path of BLOCKS) {
        expect(keysOf(locale, path)).toEqual(keysOf(en, path));
      }
    },
  );

  it.each(Object.entries(LOCALES))(
    '%s is translated, not an English copy',
    (_name, locale) => {
      const source = block(en, 'settings.connectors');
      const target = block(locale, 'settings.connectors');
      expect(target.subtitle).not.toBe(source.subtitle);
      expect((target.status as Tree).connect).not.toBe(
        (source.status as Tree).connect,
      );
    },
  );

  it.each(Object.entries({ en, ...LOCALES }))(
    '%s has no em dash in connector strings',
    (_name, locale) => {
      for (const path of BLOCKS) {
        for (const value of values(block(locale, path))) {
          expect(value).not.toContain('—');
        }
      }
    },
  );
});
