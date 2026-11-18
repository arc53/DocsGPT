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
  connectedByText,
  connectionCan,
  connectionPauseText,
  isConnectionPaused,
  isTeamConnection,
} from './teamConnections';
import type { Connection } from './types';

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

const row = (extra: Partial<Connection> = {}) =>
  ({ id: 'c1', status: 'connected', ...extra }) as Connection;

const teamRow = (extra: Partial<Connection> = {}) =>
  row({
    owner: 'team',
    team_id: 't1',
    connected_by: { user_id: 'lena', label: 'lena@example.com' },
    allowed_actions: ['view'],
    can_pick: false,
    paused_for: null,
    ...extra,
  });

describe('team connection helpers', () => {
  it('tells a team connection from a personal one', () => {
    expect(isTeamConnection(teamRow())).toBe(true);
    expect(isTeamConnection(row({ owner: 'personal' }))).toBe(false);
    // A server from before team connections sends no owner.
    expect(isTeamConnection(row())).toBe(false);
  });

  it('lets a team member do only what the server allows', () => {
    const viewer = teamRow();
    expect(connectionCan(viewer, 'view')).toBe(true);
    expect(connectionCan(viewer, 'sync')).toBe(false);
    expect(connectionCan(viewer, 'manage')).toBe(false);
    expect(connectionCan(viewer, 'pick')).toBe(false);
    const admin = teamRow({ allowed_actions: ['view', 'sync', 'manage'] });
    expect(connectionCan(admin, 'manage')).toBe(true);
    // Picking goes by `can_pick`, which is off while the account is paused.
    const picker = teamRow({
      allowed_actions: ['view', 'sync', 'manage', 'pick'],
      can_pick: false,
      status: 'paused',
    });
    expect(connectionCan(picker, 'pick')).toBe(false);
    expect(connectionCan({ ...picker, can_pick: true }, 'pick')).toBe(true);
  });

  it('lets the caller do everything with their own connection on an older server', () => {
    expect(connectionCan(row(), 'manage')).toBe(true);
    expect(connectionCan(row(), 'pick')).toBe(true);
    // A team row without the fields allows nothing: fail closed.
    expect(connectionCan(row({ owner: 'team' }), 'manage')).toBe(false);
    expect(connectionCan(row({ owner: 'team' }), 'pick')).toBe(false);
  });

  it('reads a paused account from its status or its reason', () => {
    expect(isConnectionPaused(teamRow())).toBe(false);
    expect(isConnectionPaused(teamRow({ status: 'paused' }))).toBe(true);
    expect(
      isConnectionPaused(
        teamRow({ paused_for: { reason: 'no_payer', until: null } }),
      ),
    ).toBe(true);
  });

  it('says who connected a team account', () => {
    expect(connectedByText(t, teamRow(), 'me')).toBe(
      'Connected by lena@example.com',
    );
    expect(connectedByText(t, teamRow(), 'lena')).toBe('Connected by you');
    expect(connectedByText(t, row({ owner: 'personal' }), 'me')).toBe('');
    expect(connectedByText(t, teamRow({ connected_by: null }), 'me')).toBe('');
  });

  it('says why a team account is paused', () => {
    const left = teamRow({
      status: 'paused',
      paused_for: { reason: 'payer_left', until: null, left_team: true },
    });
    expect(connectionPauseText(t, left, { teamName: 'Operations' })).toBe(
      'Paused: lena@example.com left Operations.',
    );
    expect(connectionPauseText(t, left)).toBe(
      'Paused: lena@example.com left the team.',
    );
    expect(
      connectionPauseText(t, teamRow({ status: 'paused', paused_for: null })),
    ).toBe('Paused');
    expect(connectionPauseText(t, teamRow())).toBe('');
  });

  it('has the team copy in all eight languages', () => {
    const locales = { de, en, es, fr, jp, ru, zh, 'zh-TW': zhTW };
    const keys = [
      'settings.connectors.connectionStatus.paused',
      'settings.connectors.status.paused',
      'settings.connectors.team.adminOnly',
      'settings.connectors.team.connectForTeam',
      'settings.connectors.team.connectedBy',
      'settings.connectors.team.connectedByYou',
      'settings.connectors.team.emptyAdmin',
      'settings.connectors.team.emptyMember',
      'settings.connectors.team.notice',
      'settings.connectors.team.paused',
      'settings.connectors.team.pausedHintAdmin',
      'settings.connectors.team.pausedHintMember',
      'settings.connectors.team.pausedUnknown',
      'settings.connectors.team.pickerOwnerOnly',
      'settings.connectors.team.reconnect.body',
      'settings.connectors.team.reconnect.bodyUnnamed',
      'settings.connectors.team.reconnect.confirm',
      'settings.connectors.team.reconnect.dropNote',
      'settings.connectors.team.reconnect.title',
      'settings.connectors.team.teamAccount',
    ];
    Object.entries(locales).forEach(([name, locale]) => {
      keys.forEach((key) =>
        expect(typeof read(locale, key), `${name}: ${key}`).toBe('string'),
      );
      const sources = read(
        locale,
        'settings.connectors.team.reconnect',
      ) as Record<string, string>;
      expect(
        Object.keys(sources).some((key) => key.startsWith('sources_')),
        `${name}: reconnect.sources_*`,
      ).toBe(true);
    });
  });
});
