import type { TFunction } from 'i18next';

import de from '../locale/de.json';
import en from '../locale/en.json';
import es from '../locale/es.json';
import fr from '../locale/fr.json';
import jp from '../locale/jp.json';
import ru from '../locale/ru.json';
import zhTW from '../locale/zh-TW.json';
import zh from '../locale/zh.json';
import { addedByText, isTeamModel, modelCan } from './teamModels';
import type { CustomModel } from './types';

const read = (tree: unknown, key: string) =>
  key
    .split('.')
    .reduce<unknown>(
      (node, part) =>
        node && typeof node === 'object'
          ? (node as Record<string, unknown>)[part]
          : undefined,
      tree,
    );

// English with `{{name}}` filled in, as the app's i18next does.
const t = ((key: string, options: Record<string, unknown> = {}) => {
  const text = read(en, key);
  if (typeof text !== 'string') return key;
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => String(options[name]));
}) as unknown as TFunction;

const row = (extra: Partial<CustomModel> = {}) =>
  ({
    id: 'm1',
    upstream_model_id: 'mistral-large',
    display_name: 'Mistral',
    capabilities: {},
    enabled: true,
    source: 'user',
    ...extra,
  }) as CustomModel;

const teamRow = (extra: Partial<CustomModel> = {}) =>
  row({
    source: 'team',
    owner: 'team',
    team_id: 'team-1',
    created_by: { user_id: 'u-lena', label: 'lena@example.com' },
    allowed_actions: ['view', 'use'],
    ...extra,
  });

describe('team custom models', () => {
  it("tells a team's model from a person's, in the list and in the pickers", () => {
    expect(isTeamModel(teamRow())).toBe(true);
    expect(isTeamModel({ source: 'team' })).toBe(true);
    expect(isTeamModel(row())).toBe(false);
    expect(isTeamModel({ source: 'builtin' })).toBe(false);
    expect(isTeamModel(null)).toBe(false);
  });

  it('allows what the server said, and nothing more on a team row', () => {
    const member = teamRow();
    expect(modelCan(member, 'view')).toBe(true);
    expect(modelCan(member, 'use')).toBe(true);
    expect(modelCan(member, 'manage')).toBe(false);
    expect(
      modelCan(
        teamRow({ allowed_actions: ['view', 'use', 'manage'] }),
        'manage',
      ),
    ).toBe(true);
    // A team row without the field allows nothing.
    expect(modelCan(teamRow({ allowed_actions: undefined }), 'view')).toBe(
      false,
    );
    // A person's own row from a server before team models: everything.
    expect(modelCan(row(), 'manage')).toBe(true);
    expect(modelCan(row({ allowed_actions: ['view'] }), 'manage')).toBe(false);
    expect(modelCan(null, 'view')).toBe(false);
  });

  it('says who added a team model, "you" for the reader', () => {
    expect(addedByText(t, teamRow(), 'u-me')).toBe('Added by lena@example.com');
    expect(addedByText(t, teamRow(), 'u-lena')).toBe('Added by you');
    expect(
      addedByText(t, teamRow({ created_by: { user_id: 'u-x', label: '' } })),
    ).toBe('Added by u-x');
    expect(addedByText(t, teamRow({ created_by: null }))).toBe('');
    expect(addedByText(t, row())).toBe('');
  });

  it('has the team page words in all eight languages', () => {
    const locales = { de, en, es, fr, jp, ru, zh, 'zh-TW': zhTW };
    const team = read(en, 'settings.customModels.team') as Record<
      string,
      unknown
    >;
    const leaves = (node: unknown, prefix: string): string[] =>
      node && typeof node === 'object'
        ? Object.entries(node).flatMap(([key, value]) =>
            leaves(value, `${prefix}.${key}`),
          )
        : [prefix];
    const keys = leaves(team, 'settings.customModels.team');
    expect(keys.length).toBeGreaterThan(10);
    Object.entries(locales).forEach(([name, locale]) =>
      keys.forEach((key) =>
        expect(typeof read(locale, key), `${name}: ${key}`).toBe('string'),
      ),
    );
  });
});
