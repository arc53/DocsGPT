import type { TFunction } from 'i18next';

import de from '../locale/de.json';
import en from '../locale/en.json';
import es from '../locale/es.json';
import fr from '../locale/fr.json';
import jp from '../locale/jp.json';
import ru from '../locale/ru.json';
import zhTW from '../locale/zh-TW.json';
import zh from '../locale/zh.json';
import {
  CUSTOM_MODEL_CHAT_PERSONAL_ONLY_KEY,
  CUSTOM_MODEL_ERROR_KEYS,
  customModelErrorCode,
  customModelErrorMessage,
  customModelRefusedIds,
  customModelRequestError,
  isCustomModelSaveRefusal,
} from './customModelErrors';

const t = ((key: string) => key) as unknown as TFunction;

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

const ERRORS = 'settings.customModels.team.errors';

describe('custom model refusal codes', () => {
  it('maps every custom model code the server sends', () => {
    expect(Object.keys(CUSTOM_MODEL_ERROR_KEYS).sort()).toEqual([
      'api_key_required_for_new_host',
      'credentials_unreadable',
      'custom_model_admin_required',
      'custom_model_personal_only',
      'custom_model_team_only',
      'model_admin_required',
      'model_already_in_team',
      'model_not_found',
      'not_available_to_tokens',
      'team_id_required',
      'team_workspace_required',
      'workspace_not_found',
      'workspace_role_required',
    ]);
  });

  it('has words for each in all eight languages', () => {
    const locales = { de, en, es, fr, jp, ru, zh, 'zh-TW': zhTW };
    const keys = [
      ...Object.values(CUSTOM_MODEL_ERROR_KEYS),
      CUSTOM_MODEL_CHAT_PERSONAL_ONLY_KEY,
    ];
    Object.entries(locales).forEach(([name, locale]) =>
      keys.forEach((key) =>
        expect(typeof read(locale, key), `${name}: ${key}`).toBe('string'),
      ),
    );
  });

  it('reads the code from `code` (workflow save), else from `error` (agent save)', () => {
    expect(
      customModelErrorCode({
        error: "A team's agents and workflows can use the team's…",
        code: 'custom_model_personal_only',
        errors: ['…'],
      }),
    ).toBe('custom_model_personal_only');
    expect(
      customModelErrorCode({
        success: false,
        error: 'custom_model_team_only',
        message: 'server words',
        models: ['m1'],
      }),
    ).toBe('custom_model_team_only');
    expect(customModelErrorCode({ error: 'something else' })).toBeNull();
    expect(customModelErrorCode(null)).toBeNull();
    expect(customModelErrorCode('model_not_found')).toBeNull();
  });

  it('tells a save refused for its custom models from any other refusal', () => {
    expect(
      isCustomModelSaveRefusal({ code: 'custom_model_personal_only' }),
    ).toBe(true);
    expect(isCustomModelSaveRefusal({ error: 'custom_model_team_only' })).toBe(
      true,
    );
    // The same codes mean something else on other routes.
    expect(isCustomModelSaveRefusal({ error: 'workspace_role_required' })).toBe(
      false,
    );
    expect(isCustomModelSaveRefusal({ code: 'stale_write' })).toBe(false);
  });

  it('names the refused models a save sent back', () => {
    expect(
      customModelRefusedIds({
        error: 'custom_model_personal_only',
        models: ['m1', 7, 'm2'],
      }),
    ).toEqual(['m1', 'm2']);
    expect(customModelRefusedIds({ error: 'custom_model_team_only' })).toEqual(
      [],
    );
    expect(customModelRefusedIds({ error: 'model_not_found' })).toEqual([]);
  });

  it('says a known refusal in the reader’s words, never the server’s', () => {
    expect(
      customModelErrorMessage(
        t,
        {
          success: false,
          error: 'model_already_in_team',
          model_id: 'm9',
          message: 'The team already has this model',
        },
        { fallback: 'fallback' },
      ),
    ).toBe(`${ERRORS}.alreadyInTeam`);
    expect(
      customModelErrorMessage(t, {
        error: 'workspace_not_found',
        message: 'Workspace not found',
      }),
    ).toBe(`${ERRORS}.teamNotFound`);
  });

  it("falls back to the server's sentence, then to the caller's, never a 5xx's text", () => {
    expect(
      customModelErrorMessage(
        t,
        { success: false, error: "'base_url' must be a non-empty string" },
        { fallback: 'fallback' },
      ),
    ).toBe("'base_url' must be a non-empty string");
    expect(
      customModelErrorMessage(
        t,
        { error: 'invalid_owner' },
        { fallback: 'fallback' },
      ),
    ).toBe('fallback');
    expect(
      customModelErrorMessage(
        t,
        { error: 'Traceback' },
        { status: 500, fallback: 'fallback' },
      ),
    ).toBe('fallback');
    expect(customModelErrorMessage(t, undefined)).toBe('');
  });

  it('words an error the service threw from its status and body', () => {
    const error = Object.assign(new Error('model_admin_required'), {
      status: 403,
      payload: { success: false, error: 'model_admin_required' },
    });
    expect(customModelRequestError(t, error, 'fallback')).toBe(
      `${ERRORS}.modelAdminRequired`,
    );
    expect(customModelRequestError(t, new Error('network'), 'fallback')).toBe(
      'fallback',
    );
  });
});
