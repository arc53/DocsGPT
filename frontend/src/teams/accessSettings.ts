import type { TFunction } from 'i18next';

import type {
  ResourceSetting,
  ResourceType,
} from '../api/services/teamsService';

/**
 * The owner's per-resource switches ("Option A"), mirrored from
 * `SWITCHES` in `docsgpt/api/user/resource_access.py`: key and default, in
 * the order the share dialog lists them. Only used for labels, ordering and
 * a fallback before the server's `/api/resource_settings` answers; the
 * server's values always win.
 */
export const SWITCH_DEFAULTS: Record<
  ResourceType,
  ReadonlyArray<{ key: string; default: boolean }>
> = {
  agent: [
    { key: 'editors_can_share', default: false },
    { key: 'editors_can_delete', default: false },
    { key: 'editors_can_manage_access_details', default: true },
    { key: 'viewers_can_see_logs', default: false },
  ],
  source: [
    { key: 'editors_can_share', default: false },
    { key: 'editors_can_delete', default: false },
    { key: 'viewers_can_see_config', default: true },
  ],
  tool: [
    { key: 'editors_can_change_credentials', default: true },
    { key: 'editors_can_share', default: false },
    { key: 'viewers_can_use_in_agents', default: true },
  ],
  prompt: [
    { key: 'editors_can_share', default: false },
    { key: 'viewers_can_duplicate', default: true },
  ],
};

/**
 * The switches for `type`, in display order, with the server's values
 * merged over the defaults. Unknown server keys are appended.
 */
export function resolveSettings(
  type: ResourceType,
  server: ResourceSetting[] | null | undefined,
): ResourceSetting[] {
  const byKey = new Map((server ?? []).map((s) => [s.key, s]));
  const known = SWITCH_DEFAULTS[type].map((d) => {
    const s = byKey.get(d.key);
    return s ?? { key: d.key, value: d.default, default: d.default };
  });
  const extra = (server ?? []).filter(
    (s) => !SWITCH_DEFAULTS[type].some((d) => d.key === s.key),
  );
  return [...known, ...extra];
}

export const settingValue = (
  settings: ResourceSetting[],
  key: string,
): boolean => settings.find((s) => s.key === key)?.value ?? false;

/**
 * The switches the share dialog lists. A connected tool drops "Editors can
 * change credentials": its secret is on the owner's connection, which only
 * the owner can change whatever the switch says.
 */
export const shownSettings = (
  type: ResourceType,
  settings: ResourceSetting[],
  connected = false,
): ResourceSetting[] =>
  type === 'tool' && connected
    ? settings.filter((s) => s.key !== 'editors_can_change_credentials')
    : settings;

/** Whether any switch is off its default (opens Access settings by default). */
export const anyChanged = (settings: ResourceSetting[]): boolean =>
  settings.some((s) => s.value !== s.default);

/**
 * What an Editor can do on this resource, as one or two sentences: a base
 * sentence per type, then whether they may also share or delete it. Editors
 * never change a connected tool's credentials (see `shownSettings`).
 */
export function editorHint(
  t: TFunction,
  type: ResourceType,
  settings: ResourceSetting[],
  connected = false,
): string {
  const on = (key: string) => settingValue(settings, key);
  let base: string;
  if (type === 'agent') {
    base = on('editors_can_manage_access_details')
      ? t('settings.teams.editorHint.agent')
      : t('settings.teams.editorHint.agentNoAccessDetails');
  } else if (type === 'tool') {
    base =
      !connected && on('editors_can_change_credentials')
        ? t('settings.teams.editorHint.tool')
        : t('settings.teams.editorHint.toolNoCredentials');
  } else {
    base = t(`settings.teams.editorHint.${type}`);
  }
  const share = on('editors_can_share');
  let tail: string;
  if (type === 'agent' || type === 'source') {
    const del = on('editors_can_delete');
    tail = t(
      share && del
        ? 'settings.teams.editorHint.shareAndDelete'
        : share
          ? 'settings.teams.editorHint.shareOnly'
          : del
            ? 'settings.teams.editorHint.deleteOnly'
            : 'settings.teams.editorHint.noShareNoDelete',
    );
  } else {
    tail = t(
      share
        ? 'settings.teams.editorHint.share'
        : 'settings.teams.editorHint.noShare',
    );
  }
  return `${base} ${tail}`;
}

/**
 * A switch's label and description in the share dialog. `credentialMode` is
 * a connected tool's: in member mode a viewer's agent runs with the viewer's
 * own account, not the owner's credentials.
 */
export const settingCopy = (
  t: TFunction,
  type: ResourceType,
  key: string,
  credentialMode?: 'owner' | 'member',
): { label: string; description: string } => {
  const description =
    type === 'tool' &&
    key === 'viewers_can_use_in_agents' &&
    credentialMode === 'member'
      ? 'descriptionMember'
      : 'description';
  return {
    label: t(`settings.teams.accessSettings.${type}.${key}.label`, {
      defaultValue: key,
    }),
    description: t(
      `settings.teams.accessSettings.${type}.${key}.${description}`,
      { defaultValue: '' },
    ),
  };
};

/**
 * The read-only "What people here can do" lines: the viewer and editor
 * baselines, then one line per switch (a check when on, an x when off).
 */
export function capabilityLines(
  t: TFunction,
  type: ResourceType,
  settings: ResourceSetting[],
): Array<{ key: string; allowed: boolean; text: string }> {
  return [
    {
      key: 'viewers',
      allowed: true,
      text: t(`settings.teams.capabilities.${type}.viewers`),
    },
    {
      key: 'editors',
      allowed: true,
      text: t(`settings.teams.capabilities.${type}.editors`),
    },
    ...settings.map((s) => ({
      key: s.key,
      allowed: s.value,
      text: t(
        `settings.teams.capabilities.switch.${s.key}.${s.value ? 'on' : 'off'}`,
        { defaultValue: s.key },
      ),
    })),
  ];
}

// A teams API error carries the server's message; anything else (a network
// failure) falls back to the caller's generic copy. Matched by shape, not
// `instanceof`: a thunk's unwrap() rethrows a serialized plain object.
export const errorMessage = (error: unknown, fallback: string): string => {
  const e = error as { name?: unknown; message?: unknown } | null;
  return typeof e === 'object' &&
    e !== null &&
    e.name === 'TeamsApiError' &&
    typeof e.message === 'string' &&
    e.message
    ? e.message
    : fallback;
};
