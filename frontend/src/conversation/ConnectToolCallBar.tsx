import { Plug } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/button';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import type { ToolCallsType } from './types';

/**
 * The approval card's "Connect to continue" variant: a paused call to a tool
 * whose account needs signing in. Connecting keeps the call pending; Continue
 * resumes it with the new connection, Skip denies it.
 */
export default function ConnectToolCallBar({
  toolCall,
  onToolAction,
}: {
  toolCall: ToolCallsType;
  onToolAction?: (callId: string, decision: 'approved' | 'denied') => void;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const catalog = useSelector(selectConnectorCatalog);
  const loaded = useSelector(selectConnectorsLoaded);
  const connections = useSelector(selectConnections);
  const [connected, setConnected] = useState(false);
  const { launch, modals } = useConnectorLauncher({
    onConnected: () => setConnected(true),
  });
  const required = toolCall.connection_required;
  const connector = catalog.find((c) => c.key === required?.connector_key);
  const ownConnection = required?.connection_id
    ? connections.find((c) => c.id === required.connection_id)
    : undefined;
  // Connected here, or healthy again when the user comes back to the chat.
  const ready = connected || ownConnection?.status === 'connected';
  const name =
    required?.connector_name ||
    connector?.name ||
    t('conversation.toolApproval.thisService');

  useEffect(() => {
    if (!loaded) dispatch(loadConnectors({ token }));
  }, [loaded, dispatch, token]);

  const connect = () => {
    // No account yet: connect one. The caller's own account that needs
    // signing in again is reconnected right here (every tool and source on
    // it heals). MCP servers and anyone else's account go to the drawer.
    if (connector && required?.status === 'missing') {
      launch(connector);
      return;
    }
    const inPlace =
      connector?.auth_kind === 'oauth' || connector?.auth_kind === 'api_key';
    if (connector && required?.connection_id && inPlace) {
      launch(connector, {
        mode: 'reconnect',
        connectionId: required.connection_id,
      });
      return;
    }
    navigate(
      `/settings/connectors${connector ? `?connector=${encodeURIComponent(connector.key)}` : ''}`,
    );
  };

  return (
    <div className="border-border bg-muted mb-2 flex w-full flex-wrap items-center gap-3 overflow-hidden rounded-2xl border px-4 py-2.5">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {connector ? (
          <ConnectorIcon icon={connector.icon} className="size-5 shrink-0" />
        ) : (
          <Plug className="text-muted-foreground size-5 shrink-0" aria-hidden />
        )}
        <span className="text-sm">
          {t('conversation.toolApproval.connectTitle', {
            name,
            interpolation: { escapeValue: false },
          })}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {ready ? (
          <Button
            type="button"
            size="xs"
            shape="pill"
            onClick={() => onToolAction?.(toolCall.call_id, 'approved')}
          >
            {t('conversation.toolApproval.continue')}
          </Button>
        ) : (
          <Button type="button" size="xs" shape="pill" onClick={connect}>
            {t('conversation.toolApproval.connect', {
              name,
              interpolation: { escapeValue: false },
            })}
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="xs"
          shape="pill"
          onClick={() => onToolAction?.(toolCall.call_id, 'denied')}
        >
          {t('conversation.toolApproval.skip')}
        </Button>
      </div>
      {modals}
    </div>
  );
}
