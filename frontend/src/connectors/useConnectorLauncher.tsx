import { useCallback, useState, type ReactNode } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import ConfigToolModal from '../modals/ConfigToolModal';
import MCPServerModal from '../modals/MCPServerModal';
import type { AvailableToolType } from '../modals/types';
import type { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import Upload from '../upload/Upload';
import type { IngestorType } from '../upload/types/ingestor';
import { loadConnectors } from './connectorsSlice';
import type { ConnectorDefinition } from './types';

type Launch =
  | { kind: 'source'; ingestor: IngestorType }
  | { kind: 'tool'; tool: AvailableToolType }
  | { kind: 'mcp'; server?: Record<string, unknown> }
  | null;

/**
 * One way to start connecting any catalog entry, used by every entry point
 * (the Connectors page, Add Source, Add Tool). Returns `launch` and the
 * modals it drives; render `modals` once where the hook is used.
 */
export default function useConnectorLauncher({
  onConnected,
}: { onConnected?: () => void } = {}) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const [active, setActive] = useState<Launch>(null);

  const finish = useCallback(() => {
    setActive(null);
    dispatch(loadConnectors({ token }));
    onConnected?.();
  }, [dispatch, token, onConnected]);

  const launch = useCallback(
    async (connector: ConnectorDefinition) => {
      if (connector.sync_ingestor) {
        setActive({
          kind: 'source',
          ingestor: connector.sync_ingestor as IngestorType,
        });
        return;
      }
      if (
        connector.auth_kind === 'mcp' ||
        connector.auth_kind === 'mcp_oauth'
      ) {
        setActive({
          kind: 'mcp',
          server: connector.mcp_url
            ? {
                displayName: connector.name,
                server_url: connector.mcp_url,
                auth_type:
                  connector.auth_kind === 'mcp_oauth' ? 'oauth' : 'none',
                preset: true,
              }
            : undefined,
        });
        return;
      }
      const templateName = connector.tool_templates[0];
      if (!templateName) return;
      const response = await userService.getAvailableTools(token);
      const data = await response.json();
      const tool = (data.data as AvailableToolType[] | undefined)?.find(
        (candidate) => candidate.name === templateName,
      );
      if (!tool) return;
      if (Object.keys(tool.configRequirements ?? {}).length === 0) {
        // The OpenAPI connector: create the empty API tool and open it so
        // the user can import a spec (today's API Tool flow).
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
        if (body?.id) {
          navigate('/settings/tools', { state: { openToolId: body.id } });
        }
        return;
      }
      setActive({ kind: 'tool', tool });
    },
    [navigate, token],
  );

  const close = (state: ActiveState) => {
    if (state === 'INACTIVE') setActive(null);
  };

  const modals: ReactNode = (
    <>
      {active?.kind === 'source' && (
        <Upload
          receivedFile={[]}
          setModalState={close}
          isOnboarding={false}
          renderTab={null}
          close={() => setActive(null)}
          initialIngestor={active.ingestor}
          onSuccessfulUpload={finish}
          selectUploadedDoc={false}
        />
      )}
      {active?.kind === 'tool' && (
        <ConfigToolModal
          modalState="ACTIVE"
          setModalState={close}
          tool={active.tool}
          getUserTools={finish}
        />
      )}
      {active?.kind === 'mcp' && (
        <MCPServerModal
          modalState="ACTIVE"
          setModalState={close}
          server={active.server}
          onServerSaved={finish}
        />
      )}
    </>
  );

  return { launch, modals };
}
