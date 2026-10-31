import { ArrowRight } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import userService from '../api/services/userService';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Button } from '../components/ui/button';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { useLoaderState } from '../hooks';
import type { LeaveTo } from '../hooks/useLeaveGuard';
import {
  loadConnectors,
  selectConnectorCatalog,
} from '../connectors/connectorsSlice';
import ConnectionDrawer from '../connectors/ConnectionDrawer';
import ConnectorCard from '../connectors/ConnectorCard';
import ConnectorIcon from '../connectors/ConnectorIcon';
import ConnectorTile from '../connectors/ConnectorTile';
import { partsOf } from '../connectors/catalogCards';
import { connectorDescription, connectorName } from '../connectors/i18n';
import type { ConnectorDefinition } from '../connectors/types';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import PairDeviceModal from '../settings/PairDeviceModal';
import type { AppDispatch } from '../store';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ConfigToolModal from './ConfigToolModal';
import { AvailableToolType } from './types';

/**
 * Add a tool: a service to connect, a built-in tool, a custom MCP server or
 * API. Opened from the Tools page, the chat, and the builders' Tools pickers.
 *
 * Args:
 *   getUserTools: Reloads the opener's tool list (a drawer closed, a run
 *     ended with nothing new).
 *   onToolsCreated: The one way new tools come back to the opener: the ids
 *     of the tools any path created (a built-in, a configured one, a
 *     connected service or MCP server, a paired device), possibly none. It
 *     stands in for `getUserTools` after those: the opener reloads its list
 *     (and puts them on an agent, or opens the one it made).
 *   onNavigate: Leaves for a page (Browse all, the API tool editor, Try it in
 *     chat, a source in Knowledge); a builder asks first while it has unsaved
 *     work. The router's navigate otherwise.
 */
export default function AddToolModal({
  message,
  modalState,
  setModalState,
  getUserTools,
  onToolsCreated,
  onNavigate,
}: {
  message: string;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  getUserTools: () => void;
  onToolsCreated: (toolIds: string[]) => void;
  onNavigate?: LeaveTo;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const dispatch = useDispatch<AppDispatch>();
  const catalog = useSelector(selectConnectorCatalog);
  const { launch, modals: connectModals } = useConnectorLauncher({
    onConnected: onToolsCreated,
    onNavigate,
  });
  const [availableTools, setAvailableTools] = React.useState<
    AvailableToolType[]
  >([]);
  const [selectedTool, setSelectedTool] =
    React.useState<AvailableToolType | null>(null);
  const [configModalState, setConfigModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [pairModalState, setPairModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [loading, setLoading] = useLoaderState(false);
  // A connected service's drawer, opened over the Tools page.
  const [drawerKey, setDrawerKey] = React.useState<string | null>(null);
  // Tools an account's Add tools made in the open drawer.
  const drawerCreated = React.useRef<string[]>([]);

  const getAvailableTools = () => {
    setLoading(true);
    userService
      .getAvailableTools(token)
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        setAvailableTools(
          (data.data as AvailableToolType[]).filter(
            (tool) => tool.group !== 'custom',
          ),
        );
        setLoading(false);
      });
  };

  // Services come from the connector catalog (tool connectors and MCP
  // presets): they are added by connecting the service, first in the list.
  const services = catalog.filter(
    (connector) =>
      connector.publisher !== 'custom' &&
      connector.available &&
      connector.capabilities.some((c) => c === 'read' || c === 'write'),
  );
  const builtIn = availableTools.filter(
    (tool) => (tool.group ?? 'built_in') === 'built_in',
  );
  // An MCP server or an OpenAPI spec: each click makes a new tool, in place
  // (the MCP form over Tools, the API tool editor on Tools).
  const custom = catalog.filter(
    (connector) => connector.publisher === 'custom',
  );

  // A part (Jira & Confluence's actions) is managed on its parent's drawer.
  const drawerTarget = catalog.find((c) => c.key === drawerKey);
  const drawerConnector =
    (drawerTarget?.part_of &&
      catalog.find((c) => c.key === drawerTarget.part_of)) ||
    drawerTarget ||
    null;

  const openService = (connector: ConnectorDefinition) => {
    setModalState('INACTIVE');
    // Already connected: its tools exist; open its drawer to manage them.
    if (connector.connection_count > 0) {
      setDrawerKey(connector.key);
      return;
    }
    launch(connector);
  };

  const close = () => setModalState('INACTIVE');

  const handleAddTool = (tool: AvailableToolType) => {
    // ``remote_device`` is created server-side via the pairing redeem
    // endpoint, not the standard create_tool path.
    if (tool.name === 'remote_device') {
      setModalState('INACTIVE');
      setPairModalState('ACTIVE');
      return;
    }
    // A service's tool is added by connecting the service: the key goes on
    // a connection and the tool is created with write actions needing
    // approval.
    const connector = catalog.find((c) => c.key === tool.connector_key);
    if (tool.group === 'service' && connector) {
      setModalState('INACTIVE');
      launch(connector);
      return;
    }
    if (Object.keys(tool.configRequirements).length === 0) {
      userService
        .createTool(
          {
            name: tool.name,
            displayName: tool.displayName,
            description: tool.description,
            config: {},
            actions: tool.actions,
            status: true,
          },
          token,
        )
        .then((res) => {
          if (res.status === 200) {
            return res.json();
          } else {
            throw new Error(
              `Failed to create tool, status code: ${res.status}`,
            );
          }
        })
        .then((data) => {
          setModalState('INACTIVE');
          onToolsCreated([data.id]);
        })
        .catch((error) => {
          console.error('Failed to create tool:', error);
        });
    } else {
      setModalState('INACTIVE');
      setConfigModalState('ACTIVE');
    }
  };

  // A paired device's tool is made by the pairing: found by its device.
  const reportPairedDevice = async (deviceId: string) => {
    let toolIds: string[] = [];
    try {
      const response = await userService.getUserTools(token);
      if (response.ok) {
        const data = await response.json();
        const tool = (
          (data.tools ?? []) as {
            id: string;
            name: string;
            config?: { device_id?: string };
          }[]
        ).find(
          (item) =>
            item.name === 'remote_device' &&
            item.config?.device_id === deviceId,
        );
        if (tool) toolIds = [tool.id];
      }
    } catch {
      // The opener still reloads its list.
    }
    onToolsCreated(toolIds);
  };

  React.useEffect(() => {
    if (modalState === 'ACTIVE') {
      getAvailableTools();
      dispatch(loadConnectors({ token }));
    }
  }, [modalState]);

  return (
    <>
      <Modal
        open={modalState === 'ACTIVE'}
        onOpenChange={(o) => !o && close()}
        title={t('settings.tools.selectToolSetup')}
        size="xl"
        footer={<ModalActions cancelLabel={t('cancel')} onCancel={close} />}
      >
        <div className="flex flex-col gap-6">
          {loading ? (
            <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <SkeletonLoader component="addToolCards" count={6} />
            </div>
          ) : (
            <>
              {services.length > 0 && (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    as="h3"
                    size="sm"
                    title={t('settings.tools.groupService')}
                  />
                  <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {services.map((connector) => (
                      <ConnectorCard
                        key={connector.key}
                        connector={connector}
                        variant="outline"
                        onOpen={openService}
                        testId={`add-tool-service-${connector.key}`}
                      />
                    ))}
                  </div>
                </section>
              )}
              {builtIn.length > 0 && (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    as="h3"
                    size="sm"
                    title={t('settings.tools.groupBuiltIn')}
                  />
                  <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {builtIn.map((tool) => (
                      <ConnectorTile
                        key={tool.name}
                        variant="outline"
                        icon={
                          <ToolIcon
                            name={tool.name}
                            className="size-6 shrink-0"
                            title={t('settings.tools.toolIconTitle', {
                              name: tool.displayName,
                            })}
                          />
                        }
                        title={tool.displayName}
                        description={tool.description}
                        onClick={() => {
                          setSelectedTool(tool);
                          handleAddTool(tool);
                        }}
                      />
                    ))}
                  </div>
                </section>
              )}
              {custom.length > 0 && (
                <section className="flex flex-col gap-3">
                  <SectionHeader
                    as="h3"
                    size="sm"
                    title={t('agents.form.toolsPopup.groupCustom')}
                  />
                  <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {custom.map((connector) => (
                      <ConnectorTile
                        key={connector.key}
                        variant="outline"
                        icon={
                          <ConnectorIcon
                            icon={connector.icon}
                            className="size-6 shrink-0"
                          />
                        }
                        title={connectorName(t, connector)}
                        description={connectorDescription(t, connector)}
                        onClick={() => {
                          close();
                          launch(connector);
                        }}
                        testId={`add-tool-custom-${connector.key}`}
                      />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
          <Button variant="link" size="inline" className="self-start" asChild>
            <Link
              to="/settings/connectors"
              onClick={(event) => {
                close();
                // A new tab leaves the opener where it is.
                if (
                  !onNavigate ||
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.button !== 0
                )
                  return;
                event.preventDefault();
                onNavigate('/settings/connectors');
              }}
            >
              {t('settings.connectors.browseAll')}
              <ArrowRight />
            </Link>
          </Button>
        </div>
      </Modal>
      <ConnectionDrawer
        connector={drawerConnector}
        parts={drawerConnector ? partsOf(catalog, drawerConnector.key) : []}
        onClose={() => {
          setDrawerKey(null);
          // Tools the drawer's Add tools made go on, like any new tool.
          const created = drawerCreated.current;
          drawerCreated.current = [];
          if (created.length > 0) onToolsCreated(created);
          else getUserTools();
        }}
        onToolsCreated={(toolIds) => {
          drawerCreated.current = [
            ...drawerCreated.current,
            ...toolIds.filter((id) => !drawerCreated.current.includes(id)),
          ];
        }}
        onConnect={(connector, options) => {
          setDrawerKey(null);
          launch(connector, options);
        }}
        onNavigate={onNavigate}
      />
      <ConfigToolModal
        modalState={configModalState}
        setModalState={setConfigModalState}
        tool={selectedTool}
        getUserTools={getUserTools}
        onCreated={(toolId) => onToolsCreated([toolId])}
      />
      {connectModals}
      <PairDeviceModal
        modalState={pairModalState}
        setModalState={setPairModalState}
        onPaired={(deviceId) => {
          setPairModalState('INACTIVE');
          setModalState('INACTIVE');
          void reportPairedDevice(deviceId);
        }}
      />
    </>
  );
}
