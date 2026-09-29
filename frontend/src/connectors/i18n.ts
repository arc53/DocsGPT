import type { TFunction } from 'i18next';

import type { ConnectorDefinition } from './types';

/**
 * Locale key segment for a catalog key. Preset keys look like `mcp:notion`,
 * and i18next reads `:` as a namespace separator, so it becomes `_`.
 */
export const connectorLocaleKey = (key: string) => key.replace(/[:.]/g, '_');

/** The card's one-line description, translated when the locale has it. */
export const connectorDescription = (
  t: TFunction,
  connector: Pick<ConnectorDefinition, 'key' | 'description'>,
) =>
  t(`settings.connectors.descriptions.${connectorLocaleKey(connector.key)}`, {
    defaultValue: connector.description,
  });

/**
 * Whether an API-key connection's account label is a hint of the key
 * (`…abcd`) rather than an account name (GitHub names a token connection
 * after its login).
 */
export const isKeyHint = (label: string | null | undefined) =>
  !!label && label.startsWith('…');

/** An action's name in words: `get_triage_responsibility` → "Get triage responsibility". */
export const actionTitle = (name: string) => {
  const words = name.replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** The connector's name; only the two custom kinds have translated names. */
export const connectorName = (
  t: TFunction,
  connector: Pick<ConnectorDefinition, 'key' | 'name' | 'publisher'>,
) =>
  connector.publisher === 'custom'
    ? t(`settings.connectors.custom.${connectorLocaleKey(connector.key)}`, {
        defaultValue: connector.name,
      })
    : connector.name;

const BUILT_IN_ICONS: Record<string, string> = {
  google_drive: 'drive',
  share_point: 'sharepoint',
  confluence: 'confluence',
  s3: 's3',
  reddit: 'reddit',
  brave: 'tool_brave',
  telegram: 'tool_telegram',
  ntfy: 'tool_ntfy',
  postgres: 'tool_postgres',
  github: 'github',
};

/**
 * The catalog icon for a connector key, without the catalog: chat chips and
 * citations render before (or without) the Connectors data. Presets are
 * `mcp:<name>` with a `<name>` logo; a custom server falls back to a plug.
 */
export const connectorIconKey = (key: string | null | undefined) => {
  if (!key) return 'plug';
  if (BUILT_IN_ICONS[key]) return BUILT_IN_ICONS[key];
  if (key.startsWith('mcp:')) return key.slice(4);
  return 'plug';
};
