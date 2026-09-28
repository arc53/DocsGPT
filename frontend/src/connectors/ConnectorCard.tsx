import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '../components/ui/badge';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import ConnectorIcon from './ConnectorIcon';
import { connectorDescription, connectorName } from './i18n';
import type { Capability, ConnectorDefinition } from './types';

// Sync is blue, Read green, Write red: what the connection does to your data.
const CAPABILITY_VARIANT: Record<
  Capability,
  'info' | 'success' | 'destructive'
> = {
  sync: 'info',
  read: 'success',
  write: 'destructive',
};

export function CapabilityBadges({
  capabilities,
}: {
  capabilities: Capability[];
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-1">
      {capabilities.map((capability) => (
        <Badge key={capability} variant={CAPABILITY_VARIANT[capability]}>
          {t(`settings.connectors.capability.${capability}`)}
        </Badge>
      ))}
    </div>
  );
}

/** The state a catalog card ends on: a badge, or the Connect call to action. */
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
          {connector.connected_count > 1
            ? t('settings.connectors.status.connectedCount', {
                count: connector.connected_count,
              })
            : t('settings.connectors.status.connected')}
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
      return (
        <Badge variant="default">
          <Plus aria-hidden="true" />
          {t('settings.connectors.status.connect')}
        </Badge>
      );
  }
}

/**
 * A catalog tile. The whole card is the one action: it connects an
 * available service and opens the connection details for everything else.
 */
export default function ConnectorCard({
  connector,
  onOpen,
}: {
  connector: ConnectorDefinition;
  onOpen: (connector: ConnectorDefinition) => void;
}) {
  const { t } = useTranslation();
  const name = connectorName(t, connector);
  return (
    <Card
      asChild
      variant="filled"
      padding="lg"
      interactive={connector.state !== 'disabled'}
      className="h-full"
    >
      <button
        type="button"
        disabled={connector.state === 'disabled'}
        onClick={() => onOpen(connector)}
        data-testid={`connector-card-${connector.key}`}
      >
        <span className="flex w-full items-center gap-3">
          <ConnectorIcon icon={connector.icon} className="size-8 shrink-0" />
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <CardTitle className="truncate" title={name}>
              {name}
            </CardTitle>
            {connector.publisher !== 'built_in' && (
              <span className="text-muted-foreground text-xs">
                {t(`settings.connectors.publisher.${connector.publisher}`)}
              </span>
            )}
          </span>
        </span>
        <CardDescription size="xs" className="line-clamp-2">
          {connectorDescription(t, connector)}
        </CardDescription>
        <CapabilityBadges capabilities={connector.capabilities} />
        <CardFooter>
          <ConnectorStateBadge connector={connector} />
        </CardFooter>
      </button>
    </Card>
  );
}
