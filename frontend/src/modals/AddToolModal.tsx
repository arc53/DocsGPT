import { ArrowRight } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link, useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Button } from '../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { useLoaderState } from '../hooks';
import {
  loadConnectors,
  selectConnectorCatalog,
} from '../connectors/connectorsSlice';
import { ConnectorStateBadge } from '../connectors/ConnectorCard';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectorDescription, connectorName } from '../connectors/i18n';
import type { ConnectorDefinition } from '../connectors/types';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import PairDeviceModal from '../settings/PairDeviceModal';
import type { AppDispatch } from '../store';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ConfigToolModal from './ConfigToolModal';
import { AvailableToolType } from './types';

export default function AddToolModal({
  message,
  modalState,
  setModalState,
  getUserTools,
  onToolAdded,
  onDevicePaired,
}: {
  message: string;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  getUserTools: () => void;
  onToolAdded: (toolId: string) => void;
  onDevicePaired?: (deviceId: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const dispatch = useDispatch<AppDispatch>();
  const catalog = useSelector(selectConnectorCatalog);
  const { launch, modals: connectModals } = useConnectorLauncher({
    onConnected: getUserTools,
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

  const openService = (connector: ConnectorDefinition) => {
    setModalState('INACTIVE');
    // Already connected: its tools exist; open its drawer to manage them.
    if (connector.connection_count > 0) {
      navigate(
        `/settings/connectors?connector=${encodeURIComponent(connector.key)}`,
      );
      return;
    }
    launch(connector);
  };

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
          getUserTools();
          setModalState('INACTIVE');
          onToolAdded(data.id);
        })
        .catch((error) => {
          console.error('Failed to create tool:', error);
        });
    } else {
      setModalState('INACTIVE');
      setConfigModalState('ACTIVE');
    }
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
        onOpenChange={(o) => !o && setModalState('INACTIVE')}
        title={t('settings.tools.selectToolSetup')}
        size="xl"
        footer={
          <ModalActions
            footerStart={
              <Button variant="link" size="inline" asChild>
                <Link
                  to="/settings/connectors"
                  onClick={() => setModalState('INACTIVE')}
                >
                  {t('settings.tools.browseConnectors')}
                  <ArrowRight />
                </Link>
              </Button>
            }
            cancelLabel={t('cancel')}
            onCancel={() => setModalState('INACTIVE')}
            submitLabel={t('settings.connectors.addCustom')}
            onSubmit={() => {
              setModalState('INACTIVE');
              navigate('/settings/connectors?filter=custom');
            }}
          />
        }
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
                      <Card
                        asChild
                        key={connector.key}
                        variant="outline"
                        padding="lg"
                        interactive
                        className="h-44 w-full"
                      >
                        <button
                          type="button"
                          onClick={() => openService(connector)}
                          data-testid={`add-tool-service-${connector.key}`}
                        >
                          <ConnectorIcon
                            icon={connector.icon}
                            className="size-6"
                          />
                          <CardTitle
                            title={connectorName(t, connector)}
                            className="truncate"
                          >
                            {connectorName(t, connector)}
                          </CardTitle>
                          <CardDescription size="xs" className="line-clamp-2">
                            {connectorDescription(t, connector)}
                          </CardDescription>
                          <CardFooter>
                            <ConnectorStateBadge connector={connector} />
                          </CardFooter>
                        </button>
                      </Card>
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
                      <Card
                        asChild
                        key={tool.name}
                        variant="outline"
                        padding="lg"
                        interactive
                        className="h-44 w-full"
                      >
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedTool(tool);
                            handleAddTool(tool);
                          }}
                        >
                          <ToolIcon
                            name={tool.name}
                            className="size-6"
                            title={t('settings.tools.toolIconTitle', {
                              name: tool.displayName,
                            })}
                          />
                          <CardTitle
                            title={tool.displayName}
                            className="truncate capitalize"
                          >
                            {tool.displayName}
                          </CardTitle>
                          <CardDescription size="xs" className="line-clamp-3">
                            {tool.description}
                          </CardDescription>
                        </button>
                      </Card>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </Modal>
      <ConfigToolModal
        modalState={configModalState}
        setModalState={setConfigModalState}
        tool={selectedTool}
        getUserTools={getUserTools}
      />
      {connectModals}
      <PairDeviceModal
        modalState={pairModalState}
        setModalState={setPairModalState}
        onPaired={(deviceId) => {
          setPairModalState('INACTIVE');
          setModalState('INACTIVE');
          onDevicePaired?.(deviceId);
        }}
      />
    </>
  );
}
