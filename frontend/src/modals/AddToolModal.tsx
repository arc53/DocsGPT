import React, { useRef } from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import { useOutsideAlerter } from '../hooks';
import { ActiveState } from '../models/misc';
import ConfigToolModal from './ConfigToolModal';
import { AvailableToolType } from './types';
import Spinner from '../components/Spinner';
import WrapperComponent from './WrapperModal';

export default function AddToolModal({
  message,
  modalState,
  setModalState,
  getUserTools,
  onToolAdded,
}: {
  message: string;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  getUserTools: () => void;
  onToolAdded: (toolId: string) => void;
}) {
  const { t } = useTranslation();
  const modalRef = useRef<HTMLDivElement>(null);
  const [availableTools, setAvailableTools] = React.useState<
    AvailableToolType[]
  >([]);
  const [selectedTool, setSelectedTool] =
    React.useState<AvailableToolType | null>(null);
  const [configModalState, setConfigModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [loading, setLoading] = React.useState(false);

  useOutsideAlerter(modalRef, () => {
    if (modalState === 'ACTIVE') {
      setModalState('INACTIVE');
    }
  }, [modalState]);

  const getAvailableTools = () => {
    setLoading(true);
    userService
      .getAvailableTools()
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        setAvailableTools(data.data);
        setLoading(false);
      });
  };

  const handleAddTool = (tool: AvailableToolType) => {
    if (Object.keys(tool.configRequirements).length === 0) {
      userService
        .createTool({
          name: tool.name,
          displayName: tool.displayName,
          description: tool.description,
          config: {},
          actions: tool.actions,
          status: true,
        })
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
      {modalState === 'ACTIVE' && (
        <WrapperComponent
          close={() => setModalState('INACTIVE')}
          className="h-[85vh] w-[90vw] md:w-[75vw]"
        >
          <div className="flex flex-col gap-4 h-full">
            <div>
              <h2 className="font-semibold text-xl text-jet dark:text-bright-gray px-3">
                {t('settings.tools.selectToolSetup')}
              </h2>
              <div className="mt-5 flex flex-col sm:grid sm:grid-cols-3 gap-4 h-[73vh] overflow-auto px-3 py-px">
                {loading ? (
                  <div className="h-full col-span-3 flex items-center justify-center">
                    <Spinner />
                  </div>
                ) : (
                  availableTools.map((tool, index) => (
                    <div
                      role="button"
                      tabIndex={0}
                      key={index}
                      className="h-52 w-full p-6 border rounded-2xl border-silver dark:border-[#4D4E58] flex flex-col justify-between dark:bg-[#32333B] cursor-pointer hover:border-[#9d9d9d] hover:dark:border-[#717179]"
                      onClick={() => {
                        setSelectedTool(tool);
                        handleAddTool(tool);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          setSelectedTool(tool);
                          handleAddTool(tool);
                        }
                      }}
                    >
                      <div className="w-full">
                        <div className="px-1 w-full flex items-center justify-between">
                          <img
                            src={`/toolIcons/tool_${tool.name}.svg`}
                            className="h-8 w-8"
                          />
                        </div>
                        <div className="mt-[9px]">
                          <p
                            title={tool.displayName}
                            className="px-1 text-sm font-semibold text-eerie-black dark:text-white leading-relaxed capitalize truncate"
                          >
                            {tool.displayName}
                          </p>
                          <p className="mt-1 px-1 h-24 overflow-auto text-sm text-gray-600 dark:text-[#8a8a8c] leading-relaxed">
                            {tool.description}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </WrapperComponent>
      )}
      <ConfigToolModal
        modalState={configModalState}
        setModalState={setConfigModalState}
        tool={selectedTool}
        getUserTools={getUserTools}
      />
    </>
  );
}
