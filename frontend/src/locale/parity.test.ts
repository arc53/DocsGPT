import { describe, expect, it } from 'vitest';

import de from './de.json';
import en from './en.json';
import es from './es.json';
import fr from './fr.json';
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

const LOCALES = { de, es, fr, jp, ru, zh, zhTW };

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

// Intl gives es and fr a `many` category (1,000,000). A family without
// `_many` falls back to the English `_other` for those counts.
const leaves = (tree: Tree, prefix = ''): string[] =>
  Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [prefix + key]
      : leaves(value, `${prefix}${key}.`),
  );

describe('plural forms', () => {
  it.each(Object.entries({ es, fr }))(
    '%s has a _many form wherever it has _one and _other',
    (_name, locale) => {
      const keys = new Set(leaves(locale as object as Tree));
      const missing = [...keys]
        .filter((key) => key.endsWith('_other'))
        .map((key) => key.slice(0, -'_other'.length))
        .filter((base) => keys.has(`${base}_one`) && !keys.has(`${base}_many`));
      expect(missing).toEqual([]);
    },
  );
});

const entries = (tree: Tree, prefix = ''): [string, string][] =>
  Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [[prefix + key, value] as [string, string]]
      : entries(value, `${prefix}${key}.`),
  );

describe('Russian _one forms', () => {
  // ru picks _one for 21, 31, 101… as well as 1, so the form must say the
  // number: "Its tool" for 21 tools hides 20 of them.
  it('name the count wherever _other does', () => {
    const values = new Map(entries(ru as object as Tree));
    const count = /\{\{(count|formatted)\b/;
    const missing = [...values.keys()]
      .filter((key) => key.endsWith('_one'))
      .filter(
        (key) =>
          count.test(values.get(`${key.slice(0, -4)}_other`) ?? '') &&
          !count.test(values.get(key) ?? ''),
      );
    expect(missing).toEqual([]);
  });
});
