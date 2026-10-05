import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import { connectorIconKey } from '../connectors/i18n';
import { reconnectsInPlace } from '../connectors/launchRules';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { toolCallTitle } from '../utils/streamingStatusUtils';
import ToolCallCard from './ToolCallCard';
import type { ToolCallsType } from './types';

/**
 * The approval card's "Connect to continue" variant: a paused call to a tool
 * whose account needs signing in. Connecting keeps the call pending; Continue
 * resumes it with the new connection, Skip denies it. A tool that runs on its
 * owner's account can only be fixed by the owner, so it offers Skip alone.
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
  // The launcher refreshes the store whenever its dialog closes, cancelled or
  // not, so readiness comes from the connections themselves.
  const { launch, modals } = useConnectorLauncher();
  const required = toolCall.connection_required;
  const connector = catalog.find((c) => c.key === required?.connector_key);
  // A missing account is ready once one for the service works; an account
  // that needed signing in again, once it works again.
  const ready = required?.connection_id
    ? connections.some(
        (c) => c.id === required.connection_id && c.status === 'connected',
      )
    : connections.some(
        (c) =>
          c.connector_key === required?.connector_key &&
          c.status === 'connected',
      );
  const name = required?.connector_name || connector?.name || null;
  const ownerAccount = !!required?.owner_account;
  const missing = required?.status === 'missing';
  const noEscape = { interpolation: { escapeValue: false } } as const;
  useEffect(() => {
    if (!loaded) dispatch(loadConnectors({ token }));
  }, [loaded, dispatch, token]);

  const connect = () => {
    // No account yet: connect one. The caller's own account that needs
    // signing in again is reconnected right here (every tool and source on
    // it heals). Custom MCP servers and anyone else's account go to the
    // drawer.
    if (connector && required?.status === 'missing') {
      launch(connector);
      return;
    }
    const inPlace = !!connector && reconnectsInPlace(connector);
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

  // The owner's account is theirs to reconnect; Continue would resume on it
  // while it is still broken.
  let message: string;
  let state: ReactNode;
  let primary: ReactNode = null;
  if (ownerAccount) {
    message =
      required?.owner_name && name
        ? t('conversation.toolApproval.ownerReconnect', {
            name,
            owner: required.owner_name,
            ...noEscape,
          })
        : t('conversation.toolApproval.ownerReconnectGeneric');
    state = (
      <Badge variant="warning">
        {t('settings.connectors.status.reconnect')}
      </Badge>
    );
  } else if (ready) {
    message = name
      ? t('conversation.toolApproval.connectedTitle', { name, ...noEscape })
      : t('conversation.toolApproval.connectedGeneric');
    state = (
      <Badge variant="success">
        {t('settings.connectors.status.connected')}
      </Badge>
    );
    primary = (
      <Button
        type="button"
        size="xs"
        shape="pill"
        onClick={() => onToolAction?.(toolCall.call_id, 'approved')}
      >
        {t('conversation.toolApproval.continue')}
      </Button>
    );
  } else if (missing) {
    message = name
      ? t('conversation.toolApproval.connectTitle', { name, ...noEscape })
      : t('conversation.toolApproval.connectTitleGeneric');
    state = (
      <Badge variant="neutral">
        {t('conversation.toolApproval.state.notConnected')}
      </Badge>
    );
    primary = (
      <Button type="button" size="xs" shape="pill" onClick={connect}>
        {name
          ? t('conversation.toolApproval.connect', { name, ...noEscape })
          : t('settings.connectors.status.connect')}
      </Button>
    );
  } else {
    message = name
      ? t('settings.connectors.health.pickerNotice', { name, ...noEscape })
      : t('conversation.toolApproval.reconnectGeneric');
    state = (
      <Badge variant="warning">
        {t('settings.connectors.status.reconnect')}
      </Badge>
    );
    primary = (
      <Button type="button" size="xs" shape="pill" onClick={connect}>
        {t('settings.connectors.status.reconnect')}
      </Button>
    );
  }

  return (
    <ToolCallCard
      icon={
        <ConnectorIcon
          icon={connector?.icon ?? connectorIconKey(required?.connector_key)}
          className="size-5"
        />
      }
      title={toolCallTitle(
        { ...toolCall, connector_name: toolCall.connector_name ?? name },
        t,
      )}
      state={state}
      actions={
        <>
          {primary}
          <Button
            type="button"
            variant="outline"
            size="xs"
            shape="pill"
            onClick={() => onToolAction?.(toolCall.call_id, 'denied')}
          >
            {t('conversation.toolApproval.skip')}
          </Button>
        </>
      }
    >
      <p>{message}</p>
      {modals}
    </ToolCallCard>
  );
}
