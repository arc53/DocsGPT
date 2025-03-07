import React from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import CogwheelIcon from '../assets/cogwheel.svg';
import Input from '../components/Input';
import Spinner from '../components/Spinner';
import AddToolModal from '../modals/AddToolModal';
import { ActiveState } from '../models/misc';
import ToolConfig from './ToolConfig';
import { APIToolType, UserToolType } from './types';
import ToggleSwitch from '../components/ToggleSwitch';

export default function Tools() {
  const { t } = useTranslation();
  const [searchTerm, setSearchTerm] = React.useState('');
  const [addToolModalState, setAddToolModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [userTools, setUserTools] = React.useState<UserToolType[]>([]);
  const [selectedTool, setSelectedTool] = React.useState<
    UserToolType | APIToolType | null
  >(null);
  const [loading, setLoading] = React.useState(false);

  const getUserTools = () => {
    setLoading(true);
    userService
      .getUserTools()
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        setUserTools(data.tools);
        setLoading(false);
      })
      .catch((error) => {
        console.error('Error fetching tools:', error);
        setLoading(false);
      });
  };

  const updateToolStatus = (toolId: string, newStatus: boolean) => {
    userService
      .updateToolStatus({ id: toolId, status: newStatus })
      .then(() => {
        setUserTools((prevTools) =>
          prevTools.map((tool) =>
            tool.id === toolId ? { ...tool, status: newStatus } : tool,
          ),
        );
      })
      .catch((error) => {
        console.error('Failed to update tool status:', error);
      });
  };

  const handleSettingsClick = (tool: UserToolType) => {
    setSelectedTool(tool);
  };

  const handleGoBack = () => {
    setSelectedTool(null);
    getUserTools();
  };

  const handleToolAdded = (toolId: string) => {
    userService
      .getUserTools()
      .then((res) => res.json())
      .then((data) => {
        const newTool = data.tools.find(
          (tool: UserToolType) => tool.id === toolId,
        );
        if (newTool) {
          setSelectedTool(newTool);
        } else {
          console.error('Newly added tool not found');
        }
      })
      .catch((error) => console.error('Error fetching tools:', error));
  };

  React.useEffect(() => {
    getUserTools();
  }, []);
  return (
    <div>
      {selectedTool ? (
        <ToolConfig
          tool={selectedTool}
          setTool={setSelectedTool}
          handleGoBack={handleGoBack}
        />
      ) : (
        <div className="mt-8">
          <div className="flex flex-col relative">
            <div className="my-3 flex justify-between items-center gap-1">
              <div className="p-1">
                <label htmlFor="tool-search-input" className="sr-only">
                  {t('settings.tools.searchPlaceholder')}
                </label>
                <Input
                  maxLength={256}
                  placeholder={t('settings.tools.searchPlaceholder')}
                  name="Document-search-input"
                  type="text"
                  id="tool-search-input"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  borderVariant="thin"
                />
              </div>
              <button
                className="rounded-full w-[108px] h-[30px] text-sm bg-purple-30 text-white hover:bg-[#6F3FD1] flex items-center justify-center"
                onClick={() => {
                  setAddToolModalState('ACTIVE');
                }}
              >
                {t('settings.tools.addTool')}
              </button>
            </div>
            <div className="border-b border-light-silver dark:border-dim-gray mb-8 mt-5" />
            {loading ? (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-6">
                <div className="mt-24 h-32 col-span-2 lg:col-span-3 flex items-center justify-center">
                  <Spinner />
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
                {userTools
                  .filter((tool) =>
                    tool.displayName
                      .toLowerCase()
                      .includes(searchTerm.toLowerCase()),
                  )
                  .map((tool, index) => (
                    <div
                      key={index}
                      className="relative h-52 border rounded-2xl border-light-gainsboro dark:border-arsenic"
                    >
                      <div className="h-full flex flex-col p-6">
                        <button
                          onClick={() => handleSettingsClick(tool)}
                          aria-label={t('settings.tools.configureToolAria', {
                            toolName: tool.displayName,
                          })}
                          className="absolute top-4 right-4"
                        >
                          <img
                            src={CogwheelIcon}
                            alt={t('settings.tools.settingsIconAlt')}
                            className="h-[19px] w-[19px]"
                          />
                        </button>
                        <div className="flex-1">
                          <div className="flex flex-col items-start space-y-3">
                            <img
                              src={`/toolIcons/tool_${tool.name}.svg`}
                              alt={`${tool.displayName} icon`}
                              className="h-6 w-6"
                            />
                            <p
                              title={tool.displayName}
                              className="w-[calc(100%-24px)] text-[13px] font-semibold text-raisin-black-light dark:text-bright-gray capitalize truncate"
                            >
                              {tool.displayName}
                            </p>
                            <p className="h-20 overflow-auto text-[12px] text-old-silver dark:text-sonic-silver-light">
                              {tool.description}
                            </p>
                          </div>
                        </div>
                        <div className="flex justify-end pt-2">
                          <ToggleSwitch
                            checked={tool.status}
                            onChange={(checked) =>
                              updateToolStatus(tool.id, checked)
                            }
                            size="small"
                            id={`toolToggle-${index}`}
                            ariaLabel={t('settings.tools.toggleToolAria', {
                              toolName: tool.displayName,
                            })}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
          <AddToolModal
            message={t('settings.tools.selectToolSetup')}
            modalState={addToolModalState}
            setModalState={setAddToolModalState}
            getUserTools={getUserTools}
            onToolAdded={handleToolAdded}
          />
        </div>
      )}
    </div>
  );
}
