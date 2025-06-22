import React, { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { useOutsideAlerter } from '../hooks';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ConfigToolModal from './ConfigToolModal';
import { AvailableToolType } from './types';
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
  const token = useSelector(selectToken);
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
      {modalState === 'ACTIVE' && (
        <WrapperComponent
          close={() => setModalState('INACTIVE')}
          className="h-[85vh] w-[90vw] max-w-[950px] md:w-[85vw] lg:w-[75vw]"
        >
          <div className="flex h-full flex-col">
            <div>
              <h2 className="text-jet dark:text-bright-gray px-3 text-xl font-semibold">
                {t('settings.tools.selectToolSetup')}
              </h2>
              <div className="mt-5 h-[73vh] overflow-auto px-3 py-px">
                {loading ? (
                  <div className="flex h-full items-center justify-center">
                    <Spinner />
                  </div>
                ) : (
                  <div className="grid auto-rows-fr grid-cols-1 gap-4 pb-2 sm:grid-cols-2 lg:grid-cols-3">
                    {availableTools.map((tool, index) => (
                      <div
                        role="button"
                        tabIndex={0}
                        key={index}
                        className="border-light-gainsboro bg-white-3000 dark:border-arsenic dark:bg-gunmetal flex h-52 w-full cursor-pointer flex-col justify-between rounded-2xl border p-6 hover:border-[#9d9d9d] dark:hover:border-[#717179]"
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
                          <div className="flex w-full items-center justify-between px-1">
                            <img
                              src={`/toolIcons/tool_${tool.name}.svg`}
                              className="h-6 w-6"
                              alt={`${tool.name} icon`}
                            />
                          </div>
                          <div className="mt-[9px]">
                            <p
                              title={tool.displayName}
                              className="text-raisin-black-light dark:text-bright-gray truncate px-1 text-[13px] leading-relaxed font-semibold capitalize"
                            >
                              {tool.displayName}
                            </p>
                            <p className="text-old-silver dark:text-sonic-silver-light mt-1 h-24 overflow-auto px-1 text-[12px] leading-relaxed">
                              {tool.description}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
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
