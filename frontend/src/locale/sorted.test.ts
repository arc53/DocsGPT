import { describe, expect, it } from 'vitest';

import de from './de.json';
import en from './en.json';
import es from './es.json';
import fr from './fr.json';
import jp from './jp.json';
import ru from './ru.json';
import zhTW from './zh-TW.json';
import zh from './zh.json';

// Sorted keys keep two pull requests that each add a string from meeting at
// the end of a section. `npm run locale:sort` puts a file back in order.
type Tree = { [key: string]: string | Tree };

const LOCALES = { de, en, es, fr, jp, ru, zh, zhTW };

const unsortedPaths = (tree: Tree, prefix = ''): string[] =>
  Object.entries(tree).flatMap(([key, value], index, entries) => {
    const here = index > 0 && entries[index - 1][0] > key ? [prefix + key] : [];
    return typeof value === 'string'
      ? here
      : [...here, ...unsortedPaths(value, `${prefix}${key}.`)];
  });

describe('locale files', () => {
  it('reports a key that sorts before the one above it', () => {
    expect(unsortedPaths({ b: 'x', a: { d: 'x', c: 'x' } })).toEqual([
      'a',
      'a.c',
    ]);
  });

  it.each(Object.entries(LOCALES))(
    '%s has its keys in order at every level',
    (_name, locale) => {
      expect(unsortedPaths(locale as Tree)).toEqual([]);
    },
  );
});
