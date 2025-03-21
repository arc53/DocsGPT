import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import CogwheelIcon from '../assets/cogwheel.svg';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import Input from '../components/Input';
import Spinner from '../components/Spinner';
import ToggleSwitch from '../components/ToggleSwitch';
import { useDarkTheme } from '../hooks';
import AddToolModal from '../modals/AddToolModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ToolConfig from './ToolConfig';
import { APIToolType, UserToolType } from './types';

export default function Tools() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();

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
      .getUserTools(token)
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
      .updateToolStatus({ id: toolId, status: newStatus }, token)
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
      .getUserTools(token)
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
                className="rounded-full w-[108px] h-[30px] text-sm bg-purple-30 text-white hover:bg-violets-are-blue flex items-center justify-center"
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
              <div className="flex flex-wrap gap-4 justify-center sm:justify-start">
                {userTools.length === 0 ? (
                  <div className="flex flex-col items-center justify-center w-full py-12">
                    <img
                      src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                      alt="No tools found"
                      className="h-32 w-32 mx-auto mb-6"
                    />
                    <p className="text-gray-500 dark:text-gray-400 text-center text-lg">
                      {t('settings.tools.noToolsFound')}
                    </p>
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
                        className="h-52 w-[300px] p-6 border rounded-2xl border-light-gainsboro dark:border-arsenic bg-white-3000 dark:bg-transparent flex flex-col justify-between relative"
                      >
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
                        <div className="w-full">
                          <div className="px-1 w-full flex items-center">
                            <img
                              src={`/toolIcons/tool_${tool.name}.svg`}
                              alt={`${tool.displayName} icon`}
                              className="h-6 w-6"
                            />
                          </div>
                          <div className="mt-[9px]">
                            <p
                              title={tool.displayName}
                              className="px-1 text-[13px] font-semibold text-raisin-black-light dark:text-bright-gray leading-relaxed capitalize truncate"
                            >
                              {tool.displayName}
                            </p>
                            <p className="mt-1 px-1 h-24 overflow-auto text-[12px] text-old-silver dark:text-sonic-silver-light leading-relaxed">
                              {tool.description}
                            </p>
                          </div>
                        </div>
                        <div className="absolute bottom-4 right-4">
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
                    ))
                )}
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
