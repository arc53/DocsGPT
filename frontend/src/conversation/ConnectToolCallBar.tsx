import { Plug } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/button';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  loadConnectors,
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
  const [connected, setConnected] = useState(false);
  const { launch, modals } = useConnectorLauncher({
    onConnected: () => setConnected(true),
  });
  const required = toolCall.connection_required;
  const connector = catalog.find((c) => c.key === required?.connector_key);
  const name =
    required?.connector_name ||
    connector?.name ||
    t('conversation.toolApproval.thisService');

  useEffect(() => {
    if (!loaded) dispatch(loadConnectors({ token }));
  }, [loaded, dispatch, token]);

  const connect = () => {
    // A member who has no account for the service connects one. An owner's
    // existing account that needs signing in again is healed from its drawer,
    // which reconnects that same connection for every tool and source.
    if (connector && required?.status === 'missing') {
      launch(connector);
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
        {connected ? (
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
