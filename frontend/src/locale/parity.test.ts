import { describe, expect, it } from 'vitest';

import de from './de.json';
import en from './en.json';
import es from './es.json';
import jp from './jp.json';
import ru from './ru.json';
import zhTW from './zh-TW.json';
import zh from './zh.json';

type Tree = { [key: string]: string | Tree };

// Locales pluralise differently (ru has _few/_many, jp and zh only _other),
// so a key counts once whatever plural forms it carries.
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

const flatten = (tree: Tree, prefix = ''): string[] =>
  Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [prefix + key.replace(PLURAL_SUFFIX, '')]
      : flatten(value, `${prefix}${key}.`),
  );

// Admin pages stay English by design.
const userFacing = (locale: object): Set<string> =>
  new Set(flatten(locale as Tree).filter((key) => !key.startsWith('admin.')));

const LOCALES = { de, es, jp, ru, zh, zhTW };

const english = userFacing(en);

describe('locale parity with en', () => {
  it.each(Object.entries(LOCALES))(
    '%s has every user-facing key en has',
    (_name, locale) => {
      const keys = userFacing(locale);
      expect([...english].filter((key) => !keys.has(key))).toEqual([]);
    },
  );

  it.each(Object.entries(LOCALES))(
    '%s has no keys en lacks',
    (_name, locale) => {
      const keys = [...userFacing(locale)];
      expect(keys.filter((key) => !english.has(key))).toEqual([]);
    },
  );
});
