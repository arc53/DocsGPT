import { describe, expect, it } from 'vitest';

import de from './de.json';
import en from './en.json';
import es from './es.json';
import jp from './jp.json';
import ru from './ru.json';
import zhTW from './zh-TW.json';
import zh from './zh.json';

type Tree = { [key: string]: string | Tree };

const flatten = (tree: Tree, prefix = ''): string[] =>
  Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [prefix + key]
      : flatten(value, `${prefix}${key}.`),
  );

const block = (locale: object, path: string): Tree =>
  path
    .split('.')
    .reduce<Tree>((node, key) => (node[key] as Tree) ?? {}, locale as Tree);

const LOCALES = { es, de, jp, ru, zh, zhTW };

// The citation reader's strings and the pill that opens it.
const READER = 'conversation.sources.reader';

describe('citation reader locale block', () => {
  it.each(Object.entries(LOCALES))(
    '%s has the same reader keys as en',
    (_name, locale) => {
      expect(flatten(block(locale, READER)).sort()).toEqual(
        flatten(block(en, READER)).sort(),
      );
      expect(block(locale, 'conversation.sources').open).toBeTypeOf('string');
    },
  );

  it.each(Object.entries(LOCALES))(
    '%s is translated, not an English copy',
    (_name, locale) => {
      const source = block(en, READER);
      const target = block(locale, READER);
      expect(target.missing).not.toBe(source.missing);
      expect(target.back).not.toBe(source.back);
    },
  );

  it.each(Object.entries({ en, ...LOCALES }))(
    '%s keeps the pill number and token count placeholders',
    (_name, locale) => {
      expect(block(locale, 'conversation.sources').open).toContain('{{num}}');
      expect(block(locale, READER).tokens).toContain('{{tokens}}');
    },
  );
});
