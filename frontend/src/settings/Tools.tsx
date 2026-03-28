import { RefreshCcw, Trash } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Edit from '../assets/edit.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SearchIcon from '../assets/search.svg';
import ThreeDotsIcon from '../assets/three-dots.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import Spinner from '../components/Spinner';
import ToggleSwitch from '../components/ToggleSwitch';
import { useDarkTheme } from '../hooks';
import AddToolModal from '../modals/AddToolModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import MCPServerModal from '../modals/MCPServerModal';
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
  const [activeMenuId, setActiveMenuId] = React.useState<string | null>(null);
  const menuRefs = React.useRef<{
    [key: string]: React.RefObject<HTMLDivElement | null>;
  }>({});
  const [deleteModalState, setDeleteModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [toolToDelete, setToolToDelete] = React.useState<UserToolType | null>(
    null,
  );
  const [reconnectModalState, setReconnectModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [reconnectTool, setReconnectTool] = React.useState<any>(null);
  const [mcpStatuses, setMcpStatuses] = React.useState<{
    [toolId: string]: string;
  }>({});

  React.useEffect(() => {
    userTools.forEach((tool) => {
      if (!menuRefs.current[tool.id]) {
        menuRefs.current[tool.id] = React.createRef<HTMLDivElement>();
      }
    });
  }, [userTools]);

  const handleDeleteTool = (tool: UserToolType) => {
    setToolToDelete(tool);
    setDeleteModalState('ACTIVE');
  };

  const confirmDeleteTool = () => {
    if (toolToDelete) {
      userService.deleteTool({ id: toolToDelete.id }, token).then(() => {
        getUserTools();
        fetchMcpStatuses();
        setDeleteModalState('INACTIVE');
        setToolToDelete(null);
      });
    }
  };

  const handleReconnect = (tool: UserToolType) => {
    const config = tool.config as Record<string, any>;
    const oauthScopes = Array.isArray(config.oauth_scopes)
      ? config.oauth_scopes.join(', ')
      : config.oauth_scopes || '';
    setReconnectTool({
      id: tool.id,
      displayName: tool.customName || tool.displayName,
      server_url: config.server_url || '',
      auth_type: config.auth_type || 'none',
      timeout: config.timeout || 30,
      oauth_scopes: oauthScopes,
      has_encrypted_credentials: !!config.has_encrypted_credentials,
    });
    setReconnectModalState('ACTIVE');
  };

  const getMenuOptions = (tool: UserToolType): MenuOption[] => {
    const options: MenuOption[] = [
      {
        icon: Edit,
        label: t('settings.tools.edit'),
        onClick: () => handleSettingsClick(tool),
        variant: 'primary',
        iconWidth: 14,
        iconHeight: 14,
      },
      {
        icon: Trash,
        label: t('settings.tools.delete'),
        onClick: () => handleDeleteTool(tool),
        variant: 'danger',
        iconWidth: 16,
        iconHeight: 16,
      },
    ];
    if (tool.name === 'mcp_tool') {
      options.splice(1, 0, {
        icon: RefreshCcw,
        label: t('settings.tools.reconnect'),
        onClick: () => handleReconnect(tool),
        variant: 'primary',
        iconWidth: 16,
        iconHeight: 16,
        iconClassName: 'text-[#747474]',
      });
    }
    return options;
  };

  const fetchMcpStatuses = React.useCallback(() => {
    userService
      .getMCPAuthStatus(token)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.statuses) {
          setMcpStatuses(data.statuses);
        }
      })
      .catch(() => {});
  }, [token]);

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
    fetchMcpStatuses();
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
    fetchMcpStatuses();
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
          <div className="relative flex flex-col">
            <p className="text-muted-foreground mb-5 text-[15px] leading-6">
              {t('settings.tools.subtitle')}
            </p>
            <div className="my-3 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative w-full max-w-md">
                <img
                  src={SearchIcon}
                  alt=""
                  className="absolute top-1/2 left-4 h-5 w-5 -translate-y-1/2 opacity-40"
                />
                <input
                  maxLength={256}
                  placeholder={t('settings.tools.searchPlaceholder')}
                  name="Document-search-input"
                  type="text"
                  id="tool-search-input"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="border-border bg-card text-foreground placeholder:text-muted-foreground h-11 w-full rounded-full border py-2 pr-5 pl-11 text-sm shadow-[0_1px_4px_rgba(0,0,0,0.06)] transition-shadow outline-none focus:shadow-[0_2px_8px_rgba(0,0,0,0.1)] dark:shadow-none"
                />
              </div>
              <button
                className="bg-primary hover:bg-primary/90 flex h-11 min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white"
                onClick={() => {
                  setAddToolModalState('ACTIVE');
                }}
              >
                {t('settings.tools.addTool')}
              </button>
            </div>
            <div className="border-border dark:border-border mt-5 mb-8 border-b" />
            {loading ? (
              <div className="grid grid-cols-2 gap-6 lg:grid-cols-3">
                <div className="col-span-2 mt-24 flex h-32 items-center justify-center lg:col-span-3">
                  <Spinner />
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap justify-center gap-4 sm:justify-start">
                {userTools.length === 0 ? (
                  <div className="flex w-full flex-col items-center justify-center py-12">
                    <img
                      src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                      alt={t('settings.tools.noToolsFound')}
                      className="mx-auto mb-6 h-32 w-32"
                    />
                    <p className="text-center text-lg text-gray-500 dark:text-gray-400">
                      {t('settings.tools.noToolsFound')}
                    </p>
                  </div>
                ) : (
                  (() => {
                    const filtered = userTools.filter((tool) =>
                      (tool.customName || tool.displayName)
                        .toLowerCase()
                        .includes(searchTerm.toLowerCase()),
                    );
                    return filtered.length === 0 ? (
                      <div className="flex w-full flex-col items-center justify-center py-12">
                        <img
                          src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                          alt={t('settings.tools.noToolsFound')}
                          className="mx-auto mb-6 h-32 w-32"
                        />
                        <p className="text-center text-lg text-gray-500 dark:text-gray-400">
                          {t('settings.tools.noToolsFound')}
                        </p>
                      </div>
                    ) : (
                      filtered.map((tool, index) => (
                        <div
                          key={index}
                          className="bg-muted hover:bg-accent relative flex h-52 w-[300px] flex-col justify-between overflow-hidden rounded-2xl p-6"
                        >
                          <div
                            ref={menuRefs.current[tool.id]}
                            onClick={(e) => {
                              e.stopPropagation();
                              setActiveMenuId(
                                activeMenuId === tool.id ? null : tool.id,
                              );
                            }}
                            className="absolute top-4 right-4 z-10 cursor-pointer"
                          >
                            <img
                              src={ThreeDotsIcon}
                              alt={t('settings.tools.settingsIconAlt')}
                              className="h-[19px] w-[19px]"
                            />
                            <ContextMenu
                              isOpen={activeMenuId === tool.id}
                              setIsOpen={(isOpen) => {
                                setActiveMenuId(isOpen ? tool.id : null);
                              }}
                              options={getMenuOptions(tool)}
                              anchorRef={menuRefs.current[tool.id]}
                              position="bottom-right"
                              offset={{ x: 0, y: 0 }}
                            />
                          </div>
                          <div className="w-full">
                            <div className="flex w-full items-center gap-2 px-1">
                              <img
                                src={`/toolIcons/tool_${tool.name}.svg`}
                                alt={`${tool.displayName} icon`}
                                className="h-6 w-6"
                              />
                              {tool.name === 'mcp_tool' &&
                                mcpStatuses[tool.id] && (
                                  <span
                                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] leading-none font-medium ${
                                      mcpStatuses[tool.id] === 'connected'
                                        ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                                        : mcpStatuses[tool.id] === 'needs_auth'
                                          ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                                          : 'bg-gray-100 text-gray-600 dark:bg-gray-700/40 dark:text-gray-300'
                                    }`}
                                  >
                                    {mcpStatuses[tool.id] === 'connected'
                                      ? t('settings.tools.authStatus.connected')
                                      : mcpStatuses[tool.id] === 'needs_auth'
                                        ? t(
                                            'settings.tools.authStatus.needsAuth',
                                          )
                                        : t(
                                            'settings.tools.authStatus.configured',
                                          )}
                                  </span>
                                )}
                            </div>
                            <div className="mt-[9px]">
                              <p
                                title={tool.customName || tool.displayName}
                                className="text-foreground dark:text-foreground truncate px-1 text-[13px] leading-relaxed font-semibold capitalize"
                              >
                                {tool.customName || tool.displayName}
                              </p>
                              <p
                                className="text-muted-foreground mt-1 line-clamp-4 max-h-24 overflow-hidden px-1 text-[12px] leading-relaxed break-all"
                                title={tool.description}
                              >
                                {tool.description}
                              </p>
                            </div>
                          </div>
                          <div className="absolute right-4 bottom-4">
                            <ToggleSwitch
                              checked={tool.status}
                              onChange={(checked) =>
                                updateToolStatus(tool.id, checked)
                              }
                              size="small"
                              id={`toolToggle-${index}`}
                              ariaLabel={t('settings.tools.toggleToolAria', {
                                toolName: tool.customName || tool.displayName,
                              })}
                            />
                          </div>
                        </div>
                      ))
                    );
                  })()
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
          <ConfirmationModal
            message={t('settings.tools.deleteWarning', {
              toolName:
                toolToDelete?.customName || toolToDelete?.displayName || '',
            })}
            modalState={deleteModalState}
            setModalState={setDeleteModalState}
            handleSubmit={confirmDeleteTool}
            submitLabel={t('settings.tools.delete')}
            variant="danger"
          />
          <MCPServerModal
            modalState={reconnectModalState}
            setModalState={setReconnectModalState}
            server={reconnectTool}
            onServerSaved={() => {
              setReconnectTool(null);
              getUserTools();
              fetchMcpStatuses();
            }}
          />
        </div>
      )}
    </div>
  );
}
