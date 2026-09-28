import { useCallback, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import MCPServerModal from '../modals/MCPServerModal';
import type { AvailableToolType } from '../modals/types';
import type { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import ConnectWizard, { type WizardMode } from './ConnectWizard';
import { loadConnectors } from './connectorsSlice';
import type { ConnectorDefinition } from './types';

export type LaunchOptions = {
  /** `connect` a new account, `reconnect` one, or `sync` more from one. */
  mode?: Exclude<WizardMode, 'done'>;
  connectionId?: string;
  /** An existing MCP tool to reconnect through the MCP server form. */
  mcpServer?: Record<string, unknown>;
};

type Active =
  | {
      kind: 'wizard';
      connector: ConnectorDefinition;
      mode: WizardMode;
      connectionId?: string;
    }
  | {
      kind: 'mcp';
      connector: ConnectorDefinition;
      server?: Record<string, unknown>;
    }
  | null;

const isMcp = (connector: ConnectorDefinition) =>
  connector.auth_kind === 'mcp' || connector.auth_kind === 'mcp_oauth';

/**
 * The one way to start connecting a catalog entry, used by every entry point
 * (the Connectors page and drawer, Add Source, Add Tool, the chat's Connect
 * card). Returns `launch` and the modals it drives; render `modals` once.
 */
export default function useConnectorLauncher({
  onConnected,
}: { onConnected?: () => void } = {}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const [active, setActive] = useState<Active>(null);

  const refresh = useCallback(() => {
    dispatch(loadConnectors({ token }));
    onConnected?.();
  }, [dispatch, token, onConnected]);

  const launch = useCallback(
    async (connector: ConnectorDefinition, options: LaunchOptions = {}) => {
      if (isMcp(connector)) {
        setActive({
          kind: 'mcp',
          connector,
          server:
            options.mcpServer ??
            (connector.mcp_url
              ? {
                  displayName: connector.name,
                  server_url: connector.mcp_url,
                  auth_type:
                    connector.auth_kind === 'mcp_oauth' ? 'oauth' : 'none',
                  oauth_scopes: connector.oauth_scopes.join(', '),
                  preset: true,
                }
              : undefined),
        });
        return;
      }
      if (connector.key === 'custom_openapi') {
        // An OpenAPI tool starts empty; its spec import is today's API Tool
        // screen on the Tools page.
        try {
          const response = await userService.getAvailableTools(token);
          const data = await response.json();
          const tool = (data.data as AvailableToolType[] | undefined)?.find(
            (candidate) => candidate.name === 'api_tool',
          );
          if (!tool) throw new Error('api_tool is not available');
          const created = await userService.createTool(
            {
              name: tool.name,
              displayName: tool.displayName,
              description: tool.description,
              config: {},
              actions: tool.actions,
              status: true,
            },
            token,
          );
          const body = await created.json();
          if (!body?.id) throw new Error('create failed');
          navigate('/settings/tools', { state: { openToolId: body.id } });
        } catch {
          dispatch(
            showActionToast({
              variant: 'destructive',
              message: t('settings.connectors.createFailed'),
            }),
          );
        }
        return;
      }
      setActive({
        kind: 'wizard',
        connector,
        mode: options.mode ?? 'connect',
        connectionId: options.connectionId,
      });
    },
    [dispatch, navigate, t, token],
  );

  const afterMcpSave = async () => {
    if (active?.kind !== 'mcp') return;
    const connector = active.connector;
    const list = await connectorsService.listConnections(token);
    refresh();
    const connections = (list?.connections ?? []) as {
      id: string;
      connector_key: string;
      updated_at: string | null;
    }[];
    // The newest connection for this connector is the one just saved.
    const saved = connections
      .filter((c) => c.connector_key === connector.key)
      .sort((a, b) =>
        (b.updated_at ?? '').localeCompare(a.updated_at ?? ''),
      )[0];
    setActive(
      saved
        ? { kind: 'wizard', connector, mode: 'done', connectionId: saved.id }
        : null,
    );
  };

  const closeMcp = (state: ActiveState) => {
    if (state === 'INACTIVE') setActive(null);
  };

  const modals: ReactNode = (
    <>
      {active?.kind === 'wizard' && (
        <ConnectWizard
          connector={active.connector}
          mode={active.mode}
          connectionId={active.connectionId}
          onClose={() => {
            setActive(null);
            refresh();
          }}
        />
      )}
      {active?.kind === 'mcp' && (
        <MCPServerModal
          modalState="ACTIVE"
          setModalState={closeMcp}
          server={active.server}
          onServerSaved={afterMcpSave}
        />
      )}
    </>
  );

  return { launch, modals };
}
