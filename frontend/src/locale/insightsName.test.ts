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

const at = (locale: object, path: string): string =>
  path
    .split('.')
    .reduce<string | Tree>(
      (node, part) => (node as Tree)[part],
      locale as Tree,
    ) as string;

const strings = (tree: object): string[] =>
  Object.values(tree as Tree).flatMap((value) =>
    typeof value === 'string' ? [value] : strings(value),
  );

const LOCALES = { de, en, es, fr, jp, ru, zh, zhTW };

// The feature is called one thing wherever its name is shown: the agent tab
// and page title, the Settings › Insights page, and the editor section.
const NAME_KEYS = [
  'agents.pageHeader.tabs.insights',
  'settings.insights.label',
  'agents.form.sections.analytics',
];

describe('the Insights name', () => {
  it.each(Object.entries(LOCALES))(
    '%s names the tab, the page and the editor section alike',
    (_name, locale) => {
      const names = NAME_KEYS.map((key) => at(locale, key));
      expect(new Set(names).size).toBe(1);
    },
  );

  it.each(Object.entries(LOCALES))(
    '%s keeps it apart from the Analytics page name',
    (_name, locale) => {
      expect(at(locale, 'agents.pageHeader.tabs.insights')).not.toBe(
        at(locale, 'settings.analytics.label'),
      );
    },
  );

  it('is "Insights" in English, with the switch to match', () => {
    expect(at(en, 'agents.pageHeader.tabs.insights')).toBe('Insights');
    expect(at(en, 'agents.form.analytics.enable')).toBe('Collect insights');
  });

  it('no English string still says "Conversation insights"', () => {
    expect(
      strings(en).filter((value) => /conversation insights/i.test(value)),
    ).toEqual([]);
  });

  it("the editor no longer sends people to Analytics or the agent's Logs for results", () => {
    const form = (en.agents as unknown as Tree).form as Tree;
    expect(
      strings(form.analytics as Tree).filter((value) =>
        /in Analytics|in this agent's Logs/.test(value),
      ),
    ).toEqual([]);
  });
});
