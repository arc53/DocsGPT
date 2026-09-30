import { TriangleAlert } from 'lucide-react';
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { selectConnectorCatalog } from './connectorsSlice';
import { reconnectsInPlace } from './launchRules';
import useConnectorLauncher from './useConnectorLauncher';

type ConnectionRef = { id: string; connector_key: string; name: string };

/**
 * Reconnects a connection from wherever it shows up broken: in place when the
 * wizard can redo its sign-in, otherwise on its connector page. Render
 * `modals` somewhere that stays mounted (not inside a closing popover).
 */
export function useSignInAgain({
  onConnected,
}: { onConnected?: () => void } = {}) {
  const catalog = useSelector(selectConnectorCatalog);
  const navigate = useNavigate();
  const { launch, modals } = useConnectorLauncher({ onConnected });

  const reconnect = useCallback(
    (connection: Omit<ConnectionRef, 'name'>, mcpToolId?: string) => {
      const connector = catalog.find((c) => c.key === connection.connector_key);
      if (connector && reconnectsInPlace(connector)) {
        launch(connector, {
          mode: 'reconnect',
          connectionId: connection.id,
          // An MCP preset re-signs its existing tool rather than adding one.
          mcpServer: mcpToolId ? { id: mcpToolId } : undefined,
        });
        return;
      }
      // The drawer opens on this account (`connection`), not the first one.
      navigate(
        `/settings/connectors?connector=${encodeURIComponent(connection.connector_key)}&connection=${encodeURIComponent(connection.id)}`,
      );
    },
    [catalog, launch, navigate],
  );

  return { reconnect, modals };
}

/**
 * One line per connection that needs signing in again, each with Reconnect.
 * Sits in the tool pickers so a broken service is visible where it is used.
 */
export default function SignInAgainNotice({
  connections,
  onReconnect,
}: {
  connections: ConnectionRef[];
  onReconnect: (connection: ConnectionRef) => void;
}) {
  const { t } = useTranslation();
  if (connections.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {connections.map((connection) => (
        <Alert key={connection.id} variant="warning">
          <TriangleAlert />
          <AlertDescription className="flex items-center justify-between">
            <span className="mr-3 min-w-0">
              {t('settings.connectors.health.pickerNotice', {
                name: connection.name,
                interpolation: { escapeValue: false },
              })}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              className="shrink-0"
              onClick={() => onReconnect(connection)}
            >
              {t('settings.connectors.status.reconnect')}
            </Button>
          </AlertDescription>
        </Alert>
      ))}
    </div>
  );
}
