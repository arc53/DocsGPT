import React from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import CogwheelIcon from '../assets/cogwheel.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import Input from '../components/Input';
import { useDarkTheme } from '../hooks';
import AddToolModal from '../modals/AddToolModal';
import { ActiveState } from '../models/misc';
import ToolConfig from './ToolConfig';
import { UserTool } from './types';

export default function Tools() {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const [searchTerm, setSearchTerm] = React.useState('');
  const [addToolModalState, setAddToolModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [userTools, setUserTools] = React.useState<UserTool[]>([]);
  const [selectedTool, setSelectedTool] = React.useState<UserTool | null>(null);

  const getUserTools = () => {
    userService
      .getUserTools()
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        setUserTools(data.tools);
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

  const handleSettingsClick = (tool: UserTool) => {
    setSelectedTool(tool);
  };

  const handleGoBack = () => {
    setSelectedTool(null);
    getUserTools();
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
                />
              </div>
              <button
                className="rounded-full min-w-[160px] bg-purple-30 px-6 py-3 text-white hover:bg-[#6F3FD1] text-nowrap"
                onClick={() => {
                  setAddToolModalState('ACTIVE');
                }}
              >
                {t('settings.tools.addTool')}
              </button>
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-6">
              {userTools.filter((tool) =>
                tool.displayName
                  .toLowerCase()
                  .includes(searchTerm.toLowerCase()),
              ).length === 0 ? (
                <div className="mt-24 col-span-2 lg:col-span-3 text-center text-gray-500 dark:text-gray-400">
                  <img
                    src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                    alt="No tools found"
                    className="h-24 w-24 mx-auto mb-2"
                  />
                  {t('settings.tools.noToolsFound')}
                </div>
              ) : (
                userTools
                  .filter((tool) =>
                    tool.displayName
                      .toLowerCase()
                      .includes(searchTerm.toLowerCase()),
                  )
                  .map((tool, index) => (
                    <div
                      key={index}
                      className="relative h-56 w-full p-6 border rounded-2xl border-silver dark:border-silver/40 flex flex-col justify-between"
                    >
                      <div className="w-full">
                        <div className="w-full flex items-center justify-between">
                          <img
                            src={`/toolIcons/tool_${tool.name}.svg`}
                            alt={`${tool.displayName} icon`}
                            className="h-8 w-8"
                          />
                          <button
                            className="absolute top-3 right-3 cursor-pointer"
                            onClick={() => handleSettingsClick(tool)}
                            aria-label={t('settings.tools.configureToolAria', {
                              toolName: tool.displayName,
                            })}
                          >
                            <img
                              src={CogwheelIcon}
                              alt={t('settings.tools.settingsIconAlt')}
                              className="h-[19px] w-[19px]"
                            />
                          </button>
                        </div>
                        <div className="mt-[9px]">
                          <p className="text-sm font-semibold text-eerie-black dark:text-[#EEEEEE] leading-relaxed">
                            {tool.displayName}
                          </p>
                          <p className="mt-1 h-16 overflow-auto text-[13px] text-gray-600 dark:text-gray-400 leading-relaxed pr-1">
                            {tool.description}
                          </p>
                        </div>
                      </div>
                      <div className="absolute bottom-3 right-3">
                        <label
                          htmlFor={`toolToggle-${index}`}
                          className="relative inline-block h-6 w-10 cursor-pointer rounded-full bg-gray-300 dark:bg-[#D2D5DA33]/20 transition [-webkit-tap-highlight-color:_transparent] has-[:checked]:bg-[#0C9D35CC] has-[:checked]:dark:bg-[#0C9D35CC]"
                        >
                          <span className="sr-only">
                            {t('settings.tools.toggleToolAria', {
                              toolName: tool.displayName,
                            })}
                          </span>
                          <input
                            type="checkbox"
                            id={`toolToggle-${index}`}
                            className="peer sr-only"
                            checked={tool.status}
                            onChange={() =>
                              updateToolStatus(tool.id, !tool.status)
                            }
                          />
                          <span className="absolute inset-y-0 start-0 m-[3px] size-[18px] rounded-full bg-white transition-all peer-checked:start-4"></span>
                        </label>
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>
          <AddToolModal
            message={t('settings.tools.selectToolSetup')}
            modalState={addToolModalState}
            setModalState={setAddToolModalState}
            getUserTools={getUserTools}
          />
        </div>
      )}
    </div>
  );
}
