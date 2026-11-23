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
  CONNECTION_ERROR_KEYS,
  connectionErrorCode,
  connectionErrorMessage,
  connectionPausedRefusal,
  teamConnectionOutsideTools,
} from './connectionErrors';

const t = ((key: string, options?: Record<string, unknown>) =>
  options && 'tools' in options
    ? `${key}(${String(options.tools)})`
    : key) as unknown as TFunction;

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

describe('connection refusal codes', () => {
  it('maps every team connection code the server sends', () => {
    expect(Object.keys(CONNECTION_ERROR_KEYS).sort()).toEqual([
      'account_already_connected',
      'connect_personal_first',
      'connection_admin_required',
      'connection_missing',
      'connection_not_found',
      'connection_paused',
      'connection_picker_owner_only',
      'connector_personal_only',
      'invalid_owner',
      'member_mode_not_allowed',
      'team_connection_outside',
      'team_workspace_required',
    ]);
  });

  it('has words for each in all eight languages', () => {
    const locales = { de, en, es, fr, jp, ru, zh, 'zh-TW': zhTW };
    const keys = [
      ...Object.values(CONNECTION_ERROR_KEYS),
      'settings.connectors.team.errors.teamConnectionOutsideNamed',
    ];
    Object.entries(locales).forEach(([name, locale]) =>
      keys.forEach((key) =>
        expect(typeof read(locale, key), `${name}: ${key}`).toBe('string'),
      ),
    );
  });

  it('reads the code from `code`, or from `error` when the body has no code', () => {
    expect(
      connectionErrorCode({
        error: 'Paused',
        code: 'connection_paused',
      }),
    ).toBe('connection_paused');
    expect(connectionErrorCode({ error: 'connection_not_found' })).toBe(
      'connection_not_found',
    );
    expect(connectionErrorCode({ error: 'something else' })).toBeNull();
    expect(connectionErrorCode(null)).toBeNull();
    expect(connectionErrorCode('connection_paused')).toBeNull();
  });

  it('says a known refusal in the reader’s words, never the server’s', () => {
    expect(
      connectionErrorMessage(
        t,
        {
          success: false,
          error: 'connection_picker_owner_only',
          message: 'Only the person who connected it',
        },
        { fallback: 'fallback' },
      ),
    ).toBe('settings.connectors.team.errors.pickerOwnerOnly');
    expect(connectionErrorMessage(t, { error: 'connection_missing' }, {})).toBe(
      'settings.connectors.detail.syncRefusedConnectionMissing',
    );
  });

  it('names the tools that keep an agent inside the team', () => {
    const body = {
      error: 'team_connection_outside',
      code: 'team_connection_outside',
      tools: [
        { id: '1', name: 'Drive search', connector_name: 'Google Drive' },
        { id: '2', name: 'Issues', connector_name: 'GitHub' },
        { id: 3, name: null },
      ],
    };
    expect(teamConnectionOutsideTools(body)).toEqual([
      { id: '1', name: 'Drive search', connector_name: 'Google Drive' },
      { id: '2', name: 'Issues', connector_name: 'GitHub' },
    ]);
    expect(connectionErrorMessage(t, body, {})).toBe(
      'settings.connectors.team.errors.teamConnectionOutsideNamed(Drive search, Issues)',
    );
    expect(
      connectionErrorMessage(t, { error: 'team_connection_outside' }, {}),
    ).toBe('settings.connectors.team.errors.teamConnectionOutside');
    expect(teamConnectionOutsideTools({ error: 'connection_paused' })).toBe(
      null,
    );
  });

  it('reads a paused refusal: why, and which connection', () => {
    expect(
      connectionPausedRefusal({
        error: 'connection_paused',
        code: 'connection_paused',
        paused_for: { reason: 'payer_left', until: null, left_team: true },
        connection_id: 'c1',
      }),
    ).toEqual({
      paused_for: { reason: 'payer_left', until: null, left_team: true },
      connection_id: 'c1',
    });
    expect(connectionPausedRefusal({ error: 'connection_paused' })).toEqual({
      paused_for: null,
      connection_id: null,
    });
    expect(connectionPausedRefusal({ error: 'connection_missing' })).toBeNull();
  });

  it("falls back to the server's sentence, then to the caller's", () => {
    expect(
      connectionErrorMessage(
        t,
        { success: false, error: 'Unsupported provider: x' },
        { fallback: 'fallback' },
      ),
    ).toBe('Unsupported provider: x');
    expect(
      connectionErrorMessage(
        t,
        { error: 'workspace_not_found', message: 'Team not found' },
        { fallback: 'fallback' },
      ),
    ).toBe('Team not found');
    // A bare code nobody mapped is not a sentence.
    expect(
      connectionErrorMessage(
        t,
        { error: 'workspace_not_found' },
        { fallback: 'fallback' },
      ),
    ).toBe('fallback');
    // A server error's text is never shown.
    expect(
      connectionErrorMessage(
        t,
        { error: 'Traceback' },
        { status: 500, fallback: 'fallback' },
      ),
    ).toBe('fallback');
    expect(connectionErrorMessage(t, undefined, {})).toBe('');
  });
});
