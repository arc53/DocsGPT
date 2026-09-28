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
