import type { ConnectorDefinition } from './types';

/**
 * Connected and needing attention first, then what can be connected, then
 * what an admin still has to set up.
 */
export const STATE_ORDER: Record<ConnectorDefinition['state'], number> = {
  reconnect: 0,
  connected: 1,
  available: 2,
  custom: 3,
  needs_setup: 4,
  disabled: 5,
};

/** Sorts catalog cards by `STATE_ORDER`, keeping catalog order within one. */
export const byState = (a: ConnectorDefinition, b: ConnectorDefinition) =>
  STATE_ORDER[a.state] - STATE_ORDER[b.state];

/** The parts listed under a parent card (`part_of` names the parent). */
export const partsOf = (catalog: ConnectorDefinition[], key: string) =>
  catalog.filter((c) => c.part_of === key);

/**
 * One service offered two ways (Confluence sync and the Jira & Confluence
 * MCP actions) is one card. A part is shown on its own only when its
 * parent is not listed (not set up, or turned off).
 */
export const isShownUnderParent = (
  catalog: ConnectorDefinition[],
  connector: ConnectorDefinition,
) => !!connector.part_of && catalog.some((c) => c.key === connector.part_of);

/**
 * A parent card with its parts folded in: every capability of either, the
 * accounts of both, and the state that needs the reader most.
 */
export const mergeParts = (
  catalog: ConnectorDefinition[],
  connector: ConnectorDefinition,
): ConnectorDefinition => {
  const parts = partsOf(catalog, connector.key);
  if (parts.length === 0) return connector;
  const all = [connector, ...parts];
  const state = all.some((c) => c.state === 'reconnect')
    ? 'reconnect'
    : all.some((c) => c.state === 'connected')
      ? 'connected'
      : connector.state;
  return {
    ...connector,
    capabilities: Array.from(new Set(all.flatMap((c) => c.capabilities))),
    connection_count: all.reduce((n, c) => n + c.connection_count, 0),
    connected_count: all.reduce((n, c) => n + c.connected_count, 0),
    state,
  };
};

/** The catalog as the Connectors page lists it: one card per service. */
export const catalogCards = (catalog: ConnectorDefinition[]) =>
  catalog
    .filter((connector) => !isShownUnderParent(catalog, connector))
    .map((connector) => mergeParts(catalog, connector));

/**
 * The services a user can connect to sync into Knowledge, in the
 * Connectors page's order: each card with the catalog entry that syncs
 * (the card itself, or its sync part), and only where that can be
 * connected now.
 */
export const syncTargets = (catalog: ConnectorDefinition[]) =>
  catalogCards(catalog)
    .filter((card) => card.capabilities?.includes('sync'))
    .map((card) => ({
      card,
      // The card's own entry, not the merged card, which has its parts'
      // capabilities too.
      target: [
        ...catalog.filter((c) => c.key === card.key),
        ...partsOf(catalog, card.key),
      ].find((c) => c.available && c.capabilities?.includes('sync')),
    }))
    .filter(
      (
        entry,
      ): entry is { card: ConnectorDefinition; target: ConnectorDefinition } =>
        !!entry.target,
    )
    .sort((a, b) => byState(a.card, b.card));
