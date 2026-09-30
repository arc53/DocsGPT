import type { TFunction } from 'i18next';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Badge } from '../components/ui/badge';
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

/**
 * A tile's meta row: which account is connected ("2 connected" for
 * several), or a muted Connect cue for a service that can be connected.
 *
 * Args:
 *   t: The translate function.
 *   connector: The catalog entry (a merged card for a service with parts).
 *   accounts: The caller's connections of this service (and of its parts).
 *
 * Returns:
 *   The footer content, or null when there is nothing to say.
 */
export function connectorMeta(
  t: TFunction,
  connector: ConnectorDefinition,
  accounts: Connection[],
): ReactNode {
  // An available service has no footer: no badge already says it isn't
  // connected, and the whole tile is the Connect action.
  if (connector.state !== 'connected' && connector.state !== 'reconnect')
    return null;
  const count = Math.max(connector.connection_count, accounts.length);
  if (count > 1)
    return (
      <span className="min-w-0 truncate">
        {t('settings.connectors.status.connectedCount', {
          count,
          formatted: formatCount(count),
        })}
      </span>
    );
  if (accounts.length === 1) {
    const line = accountLine(t, accounts[0]);
    return (
      <span className="min-w-0 truncate" title={line}>
        {line}
      </span>
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
}: {
  connector: ConnectorDefinition;
  onOpen: (connector: ConnectorDefinition) => void;
  /** `outline` where the tile is a choice in a picker (Add a tool). */
  variant?: 'filled' | 'outline';
  testId?: string;
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
        <>
          <ConnectorStateBadge connector={connector} />
          <CapabilityBadgeItems capabilities={connector.capabilities} />
        </>
      }
      footer={connectorMeta(t, connector, accounts)}
      disabled={connector.state === 'disabled'}
      onClick={() => onOpen(connector)}
      testId={testId ?? `connector-card-${connector.key}`}
    />
  );
}
