import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Card, CardDescription, CardTitle } from '../components/ui/card';
import { Modal } from '../components/ui/modal';
import { useLoaderState } from '../hooks';
import PairDeviceModal from '../settings/PairDeviceModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ConfigToolModal from './ConfigToolModal';
import MCPServerModal from './MCPServerModal';
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
  const token = useSelector(selectToken);
  const [availableTools, setAvailableTools] = React.useState<
    AvailableToolType[]
  >([]);
  const [selectedTool, setSelectedTool] =
    React.useState<AvailableToolType | null>(null);
  const [configModalState, setConfigModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [mcpModalState, setMcpModalState] =
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
        setAvailableTools(data.data);
        setLoading(false);
      });
  };

  const handleAddTool = (tool: AvailableToolType) => {
    // ``remote_device`` is created server-side via the pairing redeem
    // endpoint, not the standard create_tool path.
    if (tool.name === 'remote_device') {
      setModalState('INACTIVE');
      setPairModalState('ACTIVE');
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
    } else if (tool.name === 'mcp_tool') {
      setModalState('INACTIVE');
      setMcpModalState('ACTIVE');
    } else {
      setModalState('INACTIVE');
      setConfigModalState('ACTIVE');
    }
  };

  React.useEffect(() => {
    if (modalState === 'ACTIVE') getAvailableTools();
  }, [modalState]);

  const handleMcpServerAdded = () => {
    getUserTools();
    setMcpModalState('INACTIVE');
  };

  return (
    <>
      <Modal
        open={modalState === 'ACTIVE'}
        onOpenChange={(o) => !o && setModalState('INACTIVE')}
        title={t('settings.tools.selectToolSetup')}
        size="xl"
      >
        <div className="flex h-full flex-col">
          <div>
            <div className="mt-5 px-3 py-px">
              {loading ? (
                <div className="grid auto-rows-fr grid-cols-1 gap-4 pb-2 sm:grid-cols-2 lg:grid-cols-3">
                  <SkeletonLoader component="addToolCards" count={6} />
                </div>
              ) : (
                <div className="grid auto-rows-fr grid-cols-1 gap-4 pb-2 sm:grid-cols-2 lg:grid-cols-3">
                  {availableTools.map((tool, index) => (
                    <Card
                      asChild
                      key={index}
                      variant="outline"
                      padding="lg"
                      interactive
                      className="h-52 w-full justify-between"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedTool(tool);
                          handleAddTool(tool);
                        }}
                      >
                        <div className="w-full">
                          <div className="flex w-full items-center justify-between px-1">
                            <ToolIcon
                              name={tool.name}
                              className="size-6"
                              title={t('settings.tools.toolIconTitle', {
                                name: tool.name,
                              })}
                            />
                          </div>
                          <div className="mt-[9px] px-1">
                            <CardTitle
                              title={tool.displayName}
                              className="truncate capitalize"
                            >
                              {tool.displayName}
                            </CardTitle>
                            <CardDescription
                              size="xs"
                              className="mt-1 h-24 overflow-auto"
                            >
                              {tool.description}
                            </CardDescription>
                          </div>
                        </div>
                      </button>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </Modal>
      <ConfigToolModal
        modalState={configModalState}
        setModalState={setConfigModalState}
        tool={selectedTool}
        getUserTools={getUserTools}
      />
      <MCPServerModal
        modalState={mcpModalState}
        setModalState={setMcpModalState}
        onServerSaved={handleMcpServerAdded}
      />
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
