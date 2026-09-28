import { ArrowRight, Plus } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import userService from '../api/services/userService';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Button } from '../components/ui/button';
import { Card, CardDescription, CardTitle } from '../components/ui/card';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { useLoaderState } from '../hooks';
import PairDeviceModal from '../settings/PairDeviceModal';
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
  const token = useSelector(selectToken);
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
    } else {
      setModalState('INACTIVE');
      setConfigModalState('ACTIVE');
    }
  };

  React.useEffect(() => {
    if (modalState === 'ACTIVE') getAvailableTools();
  }, [modalState]);

  return (
    <>
      <Modal
        open={modalState === 'ACTIVE'}
        onOpenChange={(o) => !o && setModalState('INACTIVE')}
        title={t('settings.tools.selectToolSetup')}
        size="xl"
      >
        <div className="flex flex-col gap-6">
          {loading ? (
            <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <SkeletonLoader component="addToolCards" count={6} />
            </div>
          ) : (
            (['built_in', 'service'] as const).map((group) => {
              const tools = availableTools.filter(
                (tool) => (tool.group ?? 'built_in') === group,
              );
              if (tools.length === 0) return null;
              return (
                <section key={group} className="flex flex-col gap-3">
                  <SectionHeader
                    as="h3"
                    size="sm"
                    title={
                      group === 'built_in'
                        ? t('settings.tools.groupBuiltIn')
                        : t('settings.tools.groupService')
                    }
                  />
                  <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {tools.map((tool) => (
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
              );
            })
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button variant="link" size="inline" asChild>
              <Link
                to="/settings/connectors"
                onClick={() => setModalState('INACTIVE')}
              >
                {t('settings.tools.browseConnectors')}
                <ArrowRight className="size-3" />
              </Link>
            </Button>
            <Button variant="outline-primary" shape="pill" size="sm" asChild>
              <Link
                to="/settings/connectors?filter=custom"
                onClick={() => setModalState('INACTIVE')}
              >
                <Plus />
                {t('settings.connectors.addCustom')}
              </Link>
            </Button>
          </div>
        </div>
      </Modal>
      <ConfigToolModal
        modalState={configModalState}
        setModalState={setConfigModalState}
        tool={selectedTool}
        getUserTools={getUserTools}
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
