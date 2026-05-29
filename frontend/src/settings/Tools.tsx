import { RefreshCcw, Trash } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import devicesService from '../api/services/devicesService';
import userService from '../api/services/userService';
import Edit from '../assets/edit.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SearchIcon from '../assets/search.svg';
import ThreeDotsIcon from '../assets/three-dots.svg';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Button } from '../components/ui/button';
import { Switch } from '../components/ui/switch';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Input } from '../components/ui/input';
import { useDarkTheme, useLoaderState } from '../hooks';
import AddToolModal from '../modals/AddToolModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import MCPServerModal from '../modals/MCPServerModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import RemoteDeviceConfig from './RemoteDeviceConfig';
import ToolConfig from './ToolConfig';
import { APIToolType, UserToolType } from './types';

type ToolsMenuOption = {
  icon: string | LucideIcon;
  label: string;
  onClick: () => void;
  variant: 'default' | 'destructive';
  iconWidth?: number;
  iconHeight?: number;
  iconClassName?: string;
};

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
  const [loading, setLoading] = useLoaderState(false);
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

  const handleDeleteTool = (tool: UserToolType) => {
    setToolToDelete(tool);
    setDeleteModalState('ACTIVE');
  };

  const confirmDeleteTool = () => {
    if (!toolToDelete) return;
    const afterDelete = () => {
      getUserTools();
      fetchMcpStatuses();
      setDeleteModalState('INACTIVE');
      setToolToDelete(null);
    };
    // Remote-device tools front a paired device + live session token. Revoke
    // the device server-side (marks revoked, closes any session, invalidates
    // the token, and drops the user_tools row) instead of deleting only the
    // tool row, which would leave the daemon polling with a live token.
    const deviceId =
      toolToDelete.name === 'remote_device'
        ? toolToDelete.config?.device_id
        : undefined;
    if (deviceId) {
      devicesService
        .revoke(deviceId, token)
        .then(afterDelete)
        .catch((error) => console.error('Failed to revoke device:', error));
      return;
    }
    userService.deleteTool({ id: toolToDelete.id }, token).then(afterDelete);
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

  const getMenuOptions = (tool: UserToolType): ToolsMenuOption[] => {
    const options: ToolsMenuOption[] = [
      {
        icon: Edit,
        label: t('settings.tools.edit'),
        onClick: () => handleSettingsClick(tool),
        variant: 'default',
        iconWidth: 14,
        iconHeight: 14,
      },
      {
        icon: Trash,
        label: t('settings.tools.delete'),
        onClick: () => handleDeleteTool(tool),
        variant: 'destructive',
        iconWidth: 16,
        iconHeight: 16,
      },
    ];
    if (tool.name === 'mcp_tool') {
      options.splice(1, 0, {
        icon: RefreshCcw,
        label: t('settings.tools.reconnect'),
        onClick: () => handleReconnect(tool),
        variant: 'default',
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
        // Pure builtins (agent-only, e.g. a future builtin without an
        // agentless path) carry no per-user state and only apply when
        // added to an agent, so hide them from the management page. Dual-
        // registered tools (``scheduler``: builtin + default) stay visible
        // here so the user can toggle the default off in agentless chats.
        const filtered = (data.tools || []).filter(
          (tool: UserToolType) => tool.default || !tool.builtin,
        );
        setUserTools(filtered);
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

  const handleDevicePaired = (deviceId: string) => {
    setAddToolModalState('INACTIVE');
    userService
      .getUserTools(token)
      .then((res) => res.json())
      .then((data) => {
        const newTool = data.tools.find(
          (toolItem: UserToolType) =>
            toolItem.name === 'remote_device' &&
            toolItem.config?.device_id === deviceId,
        );
        if (newTool) setSelectedTool(newTool);
        else console.error('Paired device tool not found');
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
        selectedTool.name === 'remote_device' ? (
          <RemoteDeviceConfig
            tool={selectedTool as UserToolType}
            handleGoBack={handleGoBack}
          />
        ) : (
          <ToolConfig
            tool={selectedTool}
            setTool={setSelectedTool}
            handleGoBack={handleGoBack}
          />
        )
      ) : (
        <div className="mt-8">
          <div className="relative flex flex-col">
            <p className="text-muted-foreground mb-5 text-sm leading-6">
              {t('settings.tools.subtitle')}
            </p>
            <div className="my-3 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="w-full max-w-md">
                <Input
                  maxLength={256}
                  label={t('settings.tools.searchPlaceholder')}
                  name="Document-search-input"
                  type="text"
                  id="tool-search-input"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  labelBgClassName="bg-background"
                  className="rounded-full"
                  leftIcon={
                    <img
                      src={SearchIcon}
                      alt=""
                      className="h-4 w-4 opacity-40"
                    />
                  }
                />
              </div>
              <Button
                type="button"
                className="h-11 min-w-[108px] rounded-full whitespace-normal text-white"
                onClick={() => {
                  setAddToolModalState('ACTIVE');
                }}
              >
                {t('settings.tools.addTool')}
              </Button>
            </div>
            <div className="border-border dark:border-border mt-5 mb-8 border-b" />
            {loading ? (
              <div className="flex flex-wrap justify-center gap-4 sm:justify-start">
                <SkeletonLoader component="toolCards" count={6} />
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
                          className="bg-muted hover:bg-accent relative flex h-52 w-[300px] flex-col justify-between overflow-hidden rounded-2xl p-5"
                        >
                          {!tool.default && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <button
                                  type="button"
                                  onClick={(e) => e.stopPropagation()}
                                  className="absolute top-4 right-4 z-10 cursor-pointer"
                                  aria-label={t(
                                    'settings.tools.settingsIconAlt',
                                  )}
                                >
                                  <img
                                    src={ThreeDotsIcon}
                                    alt={t('settings.tools.settingsIconAlt')}
                                    className="h-[19px] w-[19px]"
                                  />
                                </button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent
                                align="end"
                                className="min-w-[144px]"
                              >
                                {getMenuOptions(tool).map((option, idx) => {
                                  const IconCmp =
                                    typeof option.icon !== 'string'
                                      ? option.icon
                                      : null;
                                  return (
                                    <DropdownMenuItem
                                      key={idx}
                                      variant={option.variant}
                                      onSelect={() => option.onClick()}
                                    >
                                      {typeof option.icon === 'string' ? (
                                        <img
                                          src={option.icon}
                                          alt=""
                                          width={option.iconWidth ?? 16}
                                          height={option.iconHeight ?? 16}
                                          className={option.iconClassName}
                                        />
                                      ) : (
                                        IconCmp && (
                                          <IconCmp
                                            size={Math.max(
                                              option.iconWidth ?? 16,
                                              option.iconHeight ?? 16,
                                            )}
                                            strokeWidth={1.75}
                                            aria-hidden="true"
                                            className={option.iconClassName}
                                          />
                                        )
                                      )}
                                      <span>{option.label}</span>
                                    </DropdownMenuItem>
                                  );
                                })}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                          <div className="w-full">
                            <div className="flex w-full items-center gap-2 px-1">
                              <ToolIcon
                                name={tool.name}
                                title={`${tool.displayName} icon`}
                                className="h-6 w-6"
                              />
                              {tool.default && (
                                <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs leading-none font-medium text-gray-600 dark:bg-gray-700/40 dark:text-gray-300">
                                  {t('settings.tools.builtIn')}
                                </span>
                              )}
                              {tool.name === 'mcp_tool' &&
                                mcpStatuses[tool.id] && (
                                  <span
                                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs leading-none font-medium ${
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
                                className="text-foreground dark:text-foreground truncate px-1 text-sm leading-relaxed font-semibold capitalize"
                              >
                                {tool.customName || tool.displayName}
                              </p>
                              <p
                                className="text-muted-foreground mt-1 line-clamp-4 max-h-24 overflow-hidden px-1 text-xs leading-relaxed break-all"
                                title={tool.description}
                              >
                                {tool.description}
                              </p>
                            </div>
                          </div>
                          <div className="absolute right-4 bottom-4">
                            <Switch
                              checked={tool.status}
                              onCheckedChange={(checked) =>
                                updateToolStatus(tool.id, checked)
                              }
                              id={`toolToggle-${index}`}
                              aria-label={t('settings.tools.toggleToolAria', {
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
            onDevicePaired={handleDevicePaired}
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
