import type { TFunction } from 'i18next';
import type { ReactElement, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw, Search, UserRound, Zap } from 'lucide-react';
import { useSelector } from 'react-redux';

import { Badge } from '../components/ui/badge';
import { MetaItem, MetaLine } from '../components/ui/meta-line';
import { formatCount } from '../utils/dateTimeUtils';
import ConnectorIcon from './ConnectorIcon';
import ConnectorTile from './ConnectorTile';
import { partsOf } from './catalogCards';
import { selectConnections, selectConnectorCatalog } from './connectorsSlice';
import { accountLine, connectorDescription, connectorName } from './i18n';
import type { Capability, Connection, ConnectorDefinition } from './types';

/** One neutral Badge per capability, with no wrapper (for a badge row). */
export function CapabilityBadgeItems({
  capabilities,
}: {
  capabilities: Capability[];
}) {
  const { t } = useTranslation();
  return (
    <>
      {capabilities.map((capability) => (
        // What it does, in plain words; categories, not states, so neutral and
        // the status hues stay free for the state badge.
        <Badge key={capability} variant="neutral">
          {t(`settings.connectors.capabilityPlain.${capability}`)}
        </Badge>
      ))}
    </>
  );
}

export function CapabilityBadges({
  capabilities,
}: {
  capabilities: Capability[];
}) {
  return (
    <div className="flex flex-wrap gap-1">
      <CapabilityBadgeItems capabilities={capabilities} />
    </div>
  );
}

/**
 * The state a tile leads its badge row with. Nothing for a service that can
 * be connected (its footer says Connect) or a custom entry (each click makes
 * a new tool, so there is nothing to be connected).
 */
export function ConnectorStateBadge({
  connector,
}: {
  connector: ConnectorDefinition;
}) {
  const { t } = useTranslation();
  switch (connector.state) {
    case 'connected':
      return (
        <Badge variant="success">
          {t('settings.connectors.status.connected')}
        </Badge>
      );
    case 'reconnect':
      return (
        <Badge variant="warning">
          {t('settings.connectors.status.reconnect')}
        </Badge>
      );
    case 'needs_setup':
      return (
        <Badge variant="neutral">
          {t('settings.connectors.status.needsAdminSetup')}
        </Badge>
      );
    case 'disabled':
      return (
        <Badge variant="neutral">
          {t('settings.connectors.status.disabledByAdmin')}
        </Badge>
      );
    default:
      return null;
  }
}

const CAPABILITY_ICONS: Record<
  Capability,
  ReactElement<{ className?: string }>
> = {
  sync: <RefreshCw />,
  read: <Search />,
  write: <Zap />,
};

/**
 * What a service can do, as items in a tile's meta line: a short label
 * ("Syncs", "Looks up", "Acts") with its icon, the full wording on hover.
 * Facts, not states, so never Badges on a tile.
 */
export function capabilityMetaItems(
  t: TFunction,
  capabilities: Capability[],
): ReactNode[] {
  return capabilities.map((capability) => (
    <MetaItem
      key={capability}
      icon={CAPABILITY_ICONS[capability]}
      title={t(`settings.connectors.capabilityPlain.${capability}`)}
    >
      {t(`settings.connectors.capabilityShort.${capability}`)}
    </MetaItem>
  ));
}

/**
 * The account part of a tile's meta line: which account is connected ("2
 * connected" for several), or nothing for a service that isn't.
 *
 * Args:
 *   t: The translate function.
 *   connector: The catalog entry (a merged card for a service with parts).
 *   accounts: The caller's connections of this service (and of its parts).
 *
 * Returns:
 *   A `MetaItem`, or null when there is nothing to say.
 */
export function connectorMeta(
  t: TFunction,
  connector: ConnectorDefinition,
  accounts: Connection[],
): ReactNode {
  if (connector.state !== 'connected' && connector.state !== 'reconnect')
    return null;
  const count = Math.max(connector.connection_count, accounts.length);
  if (count > 1)
    return (
      <MetaItem icon={<UserRound />}>
        {t('settings.connectors.status.connectedCount', {
          count,
          formatted: formatCount(count),
        })}
      </MetaItem>
    );
  if (accounts.length === 1) {
    const line = accountLine(t, accounts[0]);
    return (
      <MetaItem icon={<UserRound />} title={line}>
        {line}
      </MetaItem>
    );
  }
  return null;
}

/**
 * A catalog tile. The whole card is the one action: it connects an
 * available service and opens the connection details for everything else.
 */
export default function ConnectorCard({
  connector,
  onOpen,
  variant = 'filled',
  testId,
  connectedBadge = true,
}: {
  connector: ConnectorDefinition;
  onOpen: (connector: ConnectorDefinition) => void;
  /** `outline` where the tile is a choice in a picker (Add a tool). */
  variant?: 'filled' | 'outline';
  testId?: string;
  /**
   * Off where a section already says Connected (the Connectors page), so the
   * pill isn't repeated on every tile there; the states that need the reader
   * keep theirs.
   */
  connectedBadge?: boolean;
}) {
  const { t } = useTranslation();
  const catalog = useSelector(selectConnectorCatalog);
  const connections = useSelector(selectConnections);
  const keys = [
    connector.key,
    ...partsOf(catalog, connector.key).map((part) => part.key),
  ];
  const accounts = connections.filter((c) => keys.includes(c.connector_key));
  return (
    <ConnectorTile
      variant={variant}
      icon={<ConnectorIcon icon={connector.icon} className="size-6 shrink-0" />}
      title={connectorName(t, connector)}
      description={connectorDescription(t, connector)}
      badges={
        connector.state === 'connected' && !connectedBadge ? undefined : (
          <ConnectorStateBadge connector={connector} />
        )
      }
      // The account, then what the service can do: facts, in the meta line.
      footer={
        <MetaLine>
          {connectorMeta(t, connector, accounts)}
          {capabilityMetaItems(t, connector.capabilities)}
        </MetaLine>
      }
      disabled={connector.state === 'disabled'}
      onClick={() => onOpen(connector)}
      testId={testId ?? `connector-card-${connector.key}`}
    />
  );
}
