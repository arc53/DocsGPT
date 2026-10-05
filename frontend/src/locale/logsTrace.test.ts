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

const traceBlock = (locale: { settings: object }): Tree =>
  ((locale.settings as Tree).logs as Tree).trace as Tree;

const keysOf = (locale: { settings: object }): string[] =>
  Array.from(new Set(flatten(traceBlock(locale)))).sort();

const LOCALES = { es, de, jp, ru, zh, zhTW };

describe('settings.logs.trace locale block', () => {
  it.each(Object.entries(LOCALES))(
    '%s has the same keys as en',
    (_name, locale) => {
      expect(keysOf(locale)).toEqual(keysOf(en));
    },
  );

  it.each(Object.entries(LOCALES))(
    '%s is translated, not an English copy',
    (_name, locale) => {
      expect(traceBlock(locale).title).not.toBe(traceBlock(en).title);
      expect((traceBlock(locale).fields as Tree).duration).not.toBe(
        (traceBlock(en).fields as Tree).duration,
      );
    },
  );

  it('every locale provides both plural forms i18next falls back through', () => {
    [en, ...Object.values(LOCALES)].forEach((locale) => {
      const chips = traceBlock(locale).chips as Tree;
      expect(chips.llmCalls_one).toBeTruthy();
      expect(chips.llmCalls_other).toBeTruthy();
    });
  });

  it('every locale labels the new log event types', () => {
    [en, ...Object.values(LOCALES)].forEach((locale) => {
      const types = ((locale.settings as Tree).logs as Tree).types as Tree;
      expect(types.search).toBeTruthy();
      expect(types.graph).toBeTruthy();
    });
  });
});
