import { useCallback, useRef, useState, type ReactNode } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import connectorsService from '../api/services/connectorsService';
import { type LeaveTo, leaveNow } from '../hooks/useLeaveGuard';
import MCPServerModal, { type McpSaved } from '../modals/MCPServerModal';
import type { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import ConnectWizard, {
  type LaunchPurpose,
  type WizardMode,
} from './ConnectWizard';
import { reloadConnectors } from './connectorsSlice';
import { connectsInWizard } from './launchRules';
import type { ConnectorDefinition } from './types';

export type LaunchOptions = {
  /** `connect` a new account, `reconnect` one, or `sync` more from one. */
  mode?: Exclude<WizardMode, 'done'>;
  connectionId?: string;
  /** An existing MCP tool to reconnect through the MCP server form. */
  mcpServer?: Record<string, unknown>;
  /**
   * Why the wizard opens. `knowledge` (Add knowledge, Knowledge's Connect a
   * service) starts a connector with tools and sync (GitHub, Linear) with
   * Sync into Knowledge on; otherwise off. A sync-only connector always
   * starts on Sync content now.
   */
  purpose?: LaunchPurpose;
  /**
   * `team`: connect (or reconnect) an account for the current team; only
   * the Connectors page in a team asks. Never inferred from the workspace:
   * the chat's Connect card connects the person's own account anywhere.
   */
  owner?: 'team';
};

type Active =
  | {
      kind: 'wizard';
      connector: ConnectorDefinition;
      mode: WizardMode;
      connectionId?: string;
      mcpToolId?: string;
      purpose?: LaunchPurpose;
      owner?: 'team';
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
 * The MCP server form's input for signing a team's server in again from its
 * connection: the server signs the team in only when the save names the
 * team's connection, and refuses one naming the tool (that is a person's
 * own save). Null for anything else.
 *
 * Args:
 *   options: The launch options.
 *
 * Returns:
 *   The server without its tool id, with `owner: 'team'` and its
 *   `connection_id`; or null.
 */
function teamReconnect(options: LaunchOptions): Record<string, unknown> | null {
  const server = options.mcpServer;
  if (
    options.owner !== 'team' ||
    !options.connectionId ||
    !server ||
    server.auth_type !== 'oauth'
  )
    return null;
  const named: Record<string, unknown> = {
    ...server,
    owner: 'team',
    connection_id: options.connectionId,
  };
  delete named.id;
  return named;
}

type LauncherCallbacks = {
  /**
   * The run connected an account, or repaired one (a reconnect), with the
   * ids of the tools it set up (the connection's tools, a saved MCP server).
   */
  onConnected?: (toolIds: string[]) => void;
  /** The run ended with nothing connected (cancelled, or closed early). */
  onCancel?: () => void;
  /** Sources a sync started from the wizard, still ingesting. */
  onSynced?: (sourceIds: string[]) => void;
  /**
   * Leaves for a page (the API tool editor, Try it in chat, Open in
   * Knowledge); an opener with unsaved work asks first. The router's
   * navigate otherwise.
   */
  onNavigate?: LeaveTo;
  /**
   * The caller's Knowledge folder a sync started here files its sources into
   * (Add knowledge inside a folder).
   */
  folderId?: string | null;
};

/**
 * The one way to start connecting a catalog entry, used by every entry point
 * (the Connectors page and drawer, Add Source, Add Tool, the chat's Connect
 * card). Returns `launch` and the modals it drives; render `modals` once.
 *
 * Args:
 *   onConnected: Called when a run ends having connected or repaired an
 *     account, with the ids of the tools it set up.
 *   onCancel: Called when a run ends with nothing connected, so an opener
 *     that stepped aside (Add knowledge) can come back.
 *   onSynced: Called with the sources a sync started from the wizard, still
 *     ingesting.
 *   onNavigate: How a run leaves for a page; the router's navigate when
 *     left out.
 *   folderId: The Knowledge folder a sync started here files into.
 */
export default function useConnectorLauncher({
  onConnected,
  onCancel,
  onSynced,
  onNavigate,
  folderId = null,
}: LauncherCallbacks = {}) {
  const dispatch = useDispatch<AppDispatch>();
  const routerNavigate = useNavigate();
  const navigate: LeaveTo =
    onNavigate ?? ((path, options) => leaveNow(routerNavigate, path, options));
  const token = useSelector(selectToken);
  const [active, setActive] = useState<Active>(null);
  // An MCP server saved in this run: its summary wizard closing is a connect.
  const mcpSaved = useRef(false);
  // The saved MCP server's tool, reported if no summary lists it.
  const mcpToolId = useRef<string | undefined>(undefined);

  // Every close reads the connections again (the team's too, in a team): a
  // cancelled run may still have signed in (the account exists, nothing was
  // set up on it).
  const refresh = useCallback(() => {
    dispatch(reloadConnectors({ token }));
  }, [dispatch, token]);

  /** End the run: tell the opener whether it connected anything. */
  const end = useCallback(
    (connected: boolean, toolIds: string[] = []) => {
      setActive(null);
      refresh();
      const saved = mcpSaved.current;
      const savedTool = mcpToolId.current;
      mcpSaved.current = false;
      mcpToolId.current = undefined;
      const ids =
        savedTool && !toolIds.includes(savedTool)
          ? [...toolIds, savedTool]
          : toolIds;
      if (connected || saved) onConnected?.(ids);
      else onCancel?.();
    },
    [refresh, onConnected, onCancel],
  );

  const launch = useCallback(
    async (connector: ConnectorDefinition, options: LaunchOptions = {}) => {
      mcpSaved.current = false;
      mcpToolId.current = undefined;
      if (connectsInWizard(connector)) {
        setActive({
          kind: 'wizard',
          connector,
          // Sync more from an account skips signing in, like any connector.
          mode: options.mode ?? 'connect',
          connectionId: options.connectionId,
          mcpToolId:
            typeof options.mcpServer?.id === 'string'
              ? options.mcpServer.id
              : undefined,
          purpose: options.purpose,
          owner: options.owner,
        });
        return;
      }
      if (isMcp(connector)) {
        setActive({
          kind: 'mcp',
          connector,
          server:
            teamReconnect(options) ??
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
        // The API tool screen on the Tools page imports the spec; the tool
        // is only created when it is saved there.
        navigate('/settings/tools', { state: { newApiTool: true } });
        return;
      }
      setActive({
        kind: 'wizard',
        connector,
        mode: options.mode ?? 'connect',
        connectionId: options.connectionId,
        purpose: options.purpose,
        owner: options.owner,
      });
    },
    [navigate],
  );

  const afterMcpSave = async (toolId?: string, teamSave?: McpSaved) => {
    if (active?.kind !== 'mcp') return;
    const connector = active.connector;
    mcpSaved.current = true;
    // Signing an existing server in again creates no tool.
    const existing =
      typeof active.server?.id === 'string' ||
      typeof active.server?.connection_id === 'string';
    mcpToolId.current = existing ? undefined : toolId;
    // A save in a team names the connection it runs on, or none for a tool
    // on each person's own sign-in: the caller's own list would name theirs.
    if (teamSave) {
      // The form closes right after this yields; the summary comes after.
      await Promise.resolve();
      if (teamSave.connectionId) {
        // The summary names the new account from the team's list.
        refresh();
        setActive({
          kind: 'wizard',
          connector,
          mode: 'done',
          connectionId: teamSave.connectionId,
          owner: 'team',
        });
      } else end(true);
      return;
    }
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
    if (saved) {
      setActive({
        kind: 'wizard',
        connector,
        mode: 'done',
        connectionId: saved.id,
      });
      return;
    }
    end(true);
  };

  const closeMcp = (state: ActiveState) => {
    if (state !== 'INACTIVE') return;
    // A save closes the form too; the summary follows (afterMcpSave).
    if (mcpSaved.current) setActive(null);
    else end(false);
  };

  const modals: ReactNode = (
    <>
      {active?.kind === 'wizard' && (
        <ConnectWizard
          connector={active.connector}
          mode={active.mode}
          connectionId={active.connectionId}
          mcpToolId={active.mcpToolId}
          purpose={active.purpose}
          owner={active.owner}
          folderId={folderId}
          onSynced={onSynced}
          onNavigate={onNavigate}
          // A wizard that does not say (an older run) connected nothing.
          onClose={(connected?: boolean, toolIds?: string[]) =>
            end(connected === true, toolIds)
          }
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
