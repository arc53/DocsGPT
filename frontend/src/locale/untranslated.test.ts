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

const strings = (tree: object, prefix = ''): [string, string][] =>
  Object.entries(tree as Tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [[prefix + key, value] as [string, string]]
      : strings(value, `${prefix}${key}.`),
  );

// Four or more words of prose, placeholders and markup aside: short labels
// can legitimately match English (a product name, "Top K"), sentences can't.
const isProse = (value: string): boolean =>
  value
    .replace(/\{\{[^}]+\}\}|<[^>]+>|`[^`]*`|https?:\/\/\S+/g, ' ')
    .split(/\s+/)
    .filter((word) => /\p{L}{2,}/u.test(word)).length >= 4;

const english = new Map(strings(en));

const LOCALES = { de, es, fr, jp, ru, zh, zhTW };

describe('locales are translated', () => {
  it.each(Object.entries(LOCALES))(
    '%s has no English sentences copied over',
    (_name, locale) => {
      const copied = strings(locale)
        .filter(([key]) => !key.startsWith('admin.'))
        .filter(([key, value]) => english.get(key) === value && isProse(value))
        .map(([key]) => key);
      expect(copied).toEqual([]);
    },
  );
});
