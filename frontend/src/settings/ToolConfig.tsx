import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import ChevronRight from '../assets/chevron-right.svg';
import CircleCheck from '../assets/circle-check.svg';
import CircleX from '../assets/circle-x.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import Trash from '../assets/trash.svg';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import ToggleSwitch from '../components/ToggleSwitch';
import { useDarkTheme } from '../hooks';
import AddActionModal from '../modals/AddActionModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import ImportSpecModal from '../modals/ImportSpecModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { areObjectsEqual } from '../utils/objectUtils';
import { APIActionType, APIToolType, UserToolType } from './types';

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-[#D1FAE5] text-[#065F46] dark:bg-[#064E3B]/60 dark:text-[#6EE7B7]',
  POST: 'bg-[#DBEAFE] text-[#1E40AF] dark:bg-[#1E3A8A]/60 dark:text-[#93C5FD]',
  PUT: 'bg-[#FEF3C7] text-[#92400E] dark:bg-[#78350F]/60 dark:text-[#FCD34D]',
  DELETE:
    'bg-[#FEE2E2] text-[#991B1B] dark:bg-[#7F1D1D]/60 dark:text-[#FCA5A5]',
  PATCH: 'bg-[#EDE9FE] text-[#5B21B6] dark:bg-[#4C1D95]/60 dark:text-[#C4B5FD]',
  HEAD: 'bg-[#F3F4F6] text-[#374151] dark:bg-[#374151]/60 dark:text-[#D1D5DB]',
  OPTIONS:
    'bg-[#F3F4F6] text-[#374151] dark:bg-[#374151]/60 dark:text-[#D1D5DB]',
};

export default function ToolConfig({
  tool,
  setTool,
  handleGoBack,
}: {
  tool: UserToolType | APIToolType;
  setTool: (tool: UserToolType | APIToolType) => void;
  handleGoBack: () => void;
}) {
  const token = useSelector(selectToken);
  const [authKey, setAuthKey] = React.useState<string>(() => {
    if (tool.name === 'mcp_tool') {
      const config = tool.config as any;
      if (config.auth_type === 'api_key') {
        return config.api_key || '';
      } else if (config.auth_type === 'bearer') {
        return config.encrypted_token || '';
      } else if (config.auth_type === 'basic') {
        return config.password || '';
      }
      return '';
    } else if ('token' in tool.config) {
      return tool.config.token;
    }
    return '';
  });
  const [customName, setCustomName] = React.useState<string>(
    tool.customName || '',
  );
  const [actionModalState, setActionModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [importModalState, setImportModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [initialState, setInitialState] = React.useState({
    customName: tool.customName || '',
    authKey: 'token' in tool.config ? tool.config.token : '',
    config: tool.config,
    actions: 'actions' in tool ? tool.actions : [],
  });
  const [hasUnsavedChanges, setHasUnsavedChanges] = React.useState(false);
  const [showUnsavedModal, setShowUnsavedModal] = React.useState(false);
  const [userActionsSearch, setUserActionsSearch] = React.useState('');
  const [expandedUserActions, setExpandedUserActions] = React.useState<
    Set<number>
  >(new Set());
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();

  const toggleUserActionExpand = (index: number) => {
    setExpandedUserActions((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(index)) {
        newSet.delete(index);
      } else {
        newSet.add(index);
      }
      return newSet;
    });
  };

  const filteredUserActions = React.useMemo(() => {
    if (!('actions' in tool) || !tool.actions) return [];
    const query = userActionsSearch.toLowerCase();
    return tool.actions
      .map((action, index) => ({ action, originalIndex: index }))
      .filter(
        ({ action }) =>
          action.name.toLowerCase().includes(query) ||
          action.description?.toLowerCase().includes(query),
      )
      .sort((a, b) => a.action.name.localeCompare(b.action.name));
  }, [tool, userActionsSearch]);

  const handleBackClick = () => {
    if (hasUnsavedChanges) {
      setShowUnsavedModal(true);
    } else {
      handleGoBack();
    }
  };

  React.useEffect(() => {
    const currentState = {
      customName,
      authKey,
      config: tool.config,
      actions: 'actions' in tool ? tool.actions : [],
    };

    setHasUnsavedChanges(!areObjectsEqual(initialState, currentState));
  }, [customName, authKey, tool]);

  const handleCheckboxChange = (actionIndex: number, property: string) => {
    setTool({
      ...tool,
      actions:
        'actions' in tool
          ? tool.actions.map((action, index) => {
              if (index === actionIndex) {
                const newFilledByLlm =
                  !action.parameters.properties[property].filled_by_llm;
                return {
                  ...action,
                  parameters: {
                    ...action.parameters,
                    properties: {
                      ...action.parameters.properties,
                      [property]: {
                        ...action.parameters.properties[property],
                        filled_by_llm: newFilledByLlm,
                        required: newFilledByLlm,
                      },
                    },
                  },
                };
              }
              return action;
            })
          : [],
    });
  };

  const handleSaveChanges = () => {
    let configToSave;
    if (tool.name === 'api_tool') {
      configToSave = tool.config;
    } else if (tool.name === 'mcp_tool') {
      configToSave = { ...tool.config } as any;
      const mcpConfig = tool.config as any;

      if (authKey.trim()) {
        if (mcpConfig.auth_type === 'api_key') {
          configToSave.api_key = authKey;
        } else if (mcpConfig.auth_type === 'bearer') {
          configToSave.encrypted_token = authKey;
        } else if (mcpConfig.auth_type === 'basic') {
          configToSave.password = authKey;
        }
      }
    } else {
      configToSave = { token: authKey };
    }

    userService
      .updateTool(
        {
          id: tool.id,
          name: tool.name,
          displayName: tool.displayName,
          customName: customName,
          description: tool.description,
          config: configToSave,
          actions: 'actions' in tool ? tool.actions : [],
          status: tool.status,
        },
        token,
      )
      .then(() => {
        // Update initialState to match current state
        setInitialState({
          customName,
          authKey,
          config: tool.config,
          actions: 'actions' in tool ? tool.actions : [],
        });
        setHasUnsavedChanges(false);
        handleGoBack();
      });
  };

  const handleDelete = () => {
    userService.deleteTool({ id: tool.id }, token).then(() => {
      handleGoBack();
    });
  };

  const handleAddNewAction = (actionName: string) => {
    const toolCopy = tool as APIToolType;

    if (toolCopy.config.actions && toolCopy.config.actions[actionName]) {
      alert(t('settings.tools.actionAlreadyExists'));
      return;
    }

    const newAction: APIActionType = {
      name: actionName,
      method: 'GET',
      url: '',
      description: '',
      body: {
        properties: {},
        type: 'object',
      },
      headers: {
        properties: {},
        type: 'object',
      },
      query_params: {
        properties: {},
        type: 'object',
      },
      active: true,
      body_content_type: 'application/json',
      body_encoding_rules: {},
    };

    setTool({
      ...toolCopy,
      config: {
        ...toolCopy.config,
        actions: { ...toolCopy.config.actions, [actionName]: newAction },
      },
    });
  };

  const handleImportActions = (actions: APIActionType[]) => {
    const toolCopy = tool as APIToolType;
    const existingActions = toolCopy.config.actions || {};
    const newActions: { [key: string]: APIActionType } = {};

    actions.forEach((action) => {
      let actionName = action.name;
      let counter = 1;
      while (existingActions[actionName] || newActions[actionName]) {
        actionName = `${action.name}_${counter}`;
        counter++;
      }
      newActions[actionName] = { ...action, name: actionName };
    });

    setTool({
      ...toolCopy,
      config: {
        ...toolCopy.config,
        actions: { ...existingActions, ...newActions },
      },
    });
  };
  return (
    <div className="scrollbar-overlay mt-8 flex flex-col gap-4">
      <div className="mb-4 flex items-center justify-between">
        <div className="text-eerie-black dark:text-bright-gray flex items-center gap-3 text-sm">
          <button
            className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
            onClick={handleBackClick}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>
          <p className="mt-px">{t('settings.tools.backToAllTools')}</p>
        </div>
        <button
          className="bg-purple-30 hover:bg-violets-are-blue rounded-full px-3 py-2 text-xs text-nowrap text-white sm:px-4 sm:py-2"
          onClick={handleSaveChanges}
        >
          {t('settings.tools.save')}
        </button>
      </div>
      {/* Custom name section */}
      <div className="mt-1">
        <p className="text-eerie-black dark:text-bright-gray text-sm font-semibold">
          {t('settings.tools.customName')}
        </p>
        <div className="relative mt-4 w-full max-w-96">
          <Input
            type="text"
            value={customName}
            onChange={(e) => setCustomName(e.target.value)}
            borderVariant="thin"
            placeholder={t('settings.tools.customNamePlaceholder')}
          />
        </div>
      </div>
      <div className="mt-1">
        {Object.keys(tool?.config).length !== 0 && tool.name !== 'api_tool' && (
          <p className="text-eerie-black dark:text-bright-gray text-sm font-semibold">
            {tool.name === 'mcp_tool'
              ? (tool.config as any)?.auth_type === 'bearer'
                ? 'Bearer Token'
                : (tool.config as any)?.auth_type === 'api_key'
                  ? 'API Key'
                  : (tool.config as any)?.auth_type === 'basic'
                    ? 'Password'
                    : t('settings.tools.authentication')
              : t('settings.tools.authentication')}
          </p>
        )}
        <div className="mt-4 flex flex-col items-start gap-2 sm:flex-row sm:items-center">
          {Object.keys(tool?.config).length !== 0 &&
            tool.name !== 'api_tool' && (
              <div className="relative w-full max-w-96">
                <Input
                  type="text"
                  value={authKey}
                  onChange={(e) => setAuthKey(e.target.value)}
                  borderVariant="thin"
                  placeholder={
                    tool.name === 'mcp_tool'
                      ? (tool.config as any)?.auth_type === 'bearer'
                        ? 'Bearer Token'
                        : (tool.config as any)?.auth_type === 'api_key'
                          ? 'API Key'
                          : (tool.config as any)?.auth_type === 'basic'
                            ? 'Password'
                            : t('modals.configTool.apiKeyPlaceholder')
                      : t('modals.configTool.apiKeyPlaceholder')
                  }
                />
              </div>
            )}
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <div className="mx-0 my-2 h-[0.8px] w-full rounded-full bg-[#C4C4C4]/40"></div>
        <div className="flex w-full flex-row items-center justify-between gap-2">
          <p className="text-eerie-black dark:text-bright-gray text-base font-semibold">
            {t('settings.tools.actions')}
          </p>
          {tool.name === 'api_tool' && (
            <div className="flex gap-2">
              <button
                onClick={() => setImportModalState('ACTIVE')}
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
              >
                {t('settings.tools.importSpec')}
              </button>
              <button
                onClick={() => setActionModalState('ACTIVE')}
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
              >
                {t('settings.tools.addAction')}
              </button>
            </div>
          )}
        </div>
        {tool.name === 'api_tool' ? (
          <>
            {tool.config.actions &&
            Object.keys(tool.config.actions).length > 0 ? (
              <APIToolConfig tool={tool as APIToolType} setTool={setTool} />
            ) : (
              <div className="flex flex-col items-center justify-center py-8">
                <img
                  src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                  alt="No actions found"
                  className="mx-auto mb-4 h-24 w-24"
                />
                <p className="text-center text-gray-500 dark:text-gray-400">
                  {t('settings.tools.noActionsFound')}
                </p>
              </div>
            )}
          </>
        ) : (
          <div className="flex flex-col gap-4">
            {'actions' in tool && tool.actions && tool.actions.length > 0 ? (
              <>
                <div className="relative">
                  <input
                    type="text"
                    value={userActionsSearch}
                    onChange={(e) => setUserActionsSearch(e.target.value)}
                    placeholder={t('settings.tools.searchActions')}
                    className="border-silver dark:border-silver/40 dark:bg-raisin-black w-full rounded-full border px-4 py-2 pl-10 text-sm outline-none focus:border-purple-500 dark:text-white dark:placeholder-gray-500"
                  />
                  <svg
                    className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-gray-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                  </svg>
                </div>

                {filteredUserActions.length === 0 && userActionsSearch && (
                  <p className="py-4 text-center text-gray-500 dark:text-gray-400">
                    {t('settings.tools.noActionsMatch')}
                  </p>
                )}

                {filteredUserActions.map(({ action, originalIndex }) => {
                  const isExpanded = expandedUserActions.has(originalIndex);
                  return (
                    <div
                      key={originalIndex}
                      className="border-silver dark:border-silver/40 w-full rounded-xl border"
                    >
                      <div
                        className={`border-silver dark:border-silver/40 flex cursor-pointer flex-wrap items-center justify-between ${isExpanded ? 'rounded-t-xl border-b' : 'rounded-xl'} bg-[#F9F9F9] px-4 py-3 dark:bg-[#28292D]`}
                        onClick={() => toggleUserActionExpand(originalIndex)}
                      >
                        <div className="flex items-center gap-3">
                          <img
                            src={ChevronRight}
                            alt="expand"
                            className={`h-4 w-4 opacity-60 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
                          />
                          <p className="text-eerie-black dark:text-bright-gray font-semibold">
                            {action.name}
                          </p>
                          {action.description && (
                            <p className="hidden truncate text-sm text-gray-500 md:block md:max-w-xs lg:max-w-md dark:text-gray-400">
                              {action.description}
                            </p>
                          )}
                        </div>
                        <div
                          className="flex items-center gap-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ToggleSwitch
                            checked={action.active}
                            onChange={(checked) => {
                              setTool({
                                ...tool,
                                actions: tool.actions.map((act, index) => {
                                  if (index === originalIndex) {
                                    return { ...act, active: checked };
                                  }
                                  return act;
                                }),
                              });
                            }}
                            size="small"
                            id={`actionToggle-${originalIndex}`}
                          />
                        </div>
                      </div>
                      {isExpanded && (
                        <>
                          <div className="relative mt-5 w-full px-5">
                            <Input
                              type="text"
                              className="w-full"
                              placeholder={t(
                                'settings.tools.descriptionPlaceholder',
                              )}
                              value={action.description}
                              onChange={(e) => {
                                setTool({
                                  ...tool,
                                  actions: tool.actions.map((act, index) => {
                                    if (index === originalIndex) {
                                      return {
                                        ...act,
                                        description: e.target.value,
                                      };
                                    }
                                    return act;
                                  }),
                                });
                              }}
                              borderVariant="thin"
                            />
                          </div>
                          <div className="px-5 py-4">
                            <table className="table-default">
                              <thead>
                                <tr>
                                  <th>{t('settings.tools.fieldName')}</th>
                                  <th>{t('settings.tools.fieldType')}</th>
                                  <th>{t('settings.tools.filledByLLM')}</th>
                                  <th>
                                    {t('settings.tools.fieldDescription')}
                                  </th>
                                  <th>{t('settings.tools.value')}</th>
                                </tr>
                              </thead>
                              <tbody>
                                {Object.entries(
                                  action.parameters?.properties,
                                ).map((param, paramIndex) => {
                                  const uniqueKey = `${originalIndex}-${param[0]}`;
                                  return (
                                    <tr
                                      key={paramIndex}
                                      className="font-normal text-nowrap"
                                    >
                                      <td>{param[0]}</td>
                                      <td>{param[1].type}</td>
                                      <td>
                                        <label
                                          htmlFor={uniqueKey}
                                          className="ml-[10px] flex cursor-pointer items-start gap-4"
                                        >
                                          <div className="flex items-center">
                                            &#8203;
                                            <input
                                              checked={param[1].filled_by_llm}
                                              id={uniqueKey}
                                              type="checkbox"
                                              className="size-4 rounded-sm border-gray-300 bg-transparent"
                                              onChange={() =>
                                                handleCheckboxChange(
                                                  originalIndex,
                                                  param[0],
                                                )
                                              }
                                            />
                                          </div>
                                        </label>
                                      </td>
                                      <td className="w-10">
                                        <input
                                          key={uniqueKey}
                                          value={param[1].description}
                                          className="border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                                          onChange={(e) => {
                                            setTool({
                                              ...tool,
                                              actions: tool.actions.map(
                                                (act, index) => {
                                                  if (index === originalIndex) {
                                                    return {
                                                      ...act,
                                                      parameters: {
                                                        ...act.parameters,
                                                        properties: {
                                                          ...act.parameters
                                                            .properties,
                                                          [param[0]]: {
                                                            ...act.parameters
                                                              .properties[
                                                              param[0]
                                                            ],
                                                            description:
                                                              e.target.value,
                                                          },
                                                        },
                                                      },
                                                    };
                                                  }
                                                  return act;
                                                },
                                              ),
                                            });
                                          }}
                                        ></input>
                                      </td>
                                      <td>
                                        <input
                                          value={param[1].value}
                                          key={uniqueKey}
                                          disabled={param[1].filled_by_llm}
                                          className={`border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden ${param[1].filled_by_llm ? 'opacity-50' : ''}`}
                                          onChange={(e) => {
                                            setTool({
                                              ...tool,
                                              actions: tool.actions.map(
                                                (act, index) => {
                                                  if (index === originalIndex) {
                                                    return {
                                                      ...act,
                                                      parameters: {
                                                        ...act.parameters,
                                                        properties: {
                                                          ...act.parameters
                                                            .properties,
                                                          [param[0]]: {
                                                            ...act.parameters
                                                              .properties[
                                                              param[0]
                                                            ],
                                                            value:
                                                              e.target.value,
                                                          },
                                                        },
                                                      },
                                                    };
                                                  }
                                                  return act;
                                                },
                                              ),
                                            });
                                          }}
                                        ></input>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-8">
                <img
                  src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                  alt="No actions found"
                  className="mx-auto mb-4 h-24 w-24"
                />
                <p className="text-center text-gray-500 dark:text-gray-400">
                  {t('settings.tools.noActionsFound')}
                </p>
              </div>
            )}
          </div>
        )}
        <AddActionModal
          modalState={actionModalState}
          setModalState={setActionModalState}
          handleSubmit={handleAddNewAction}
        />
        <ImportSpecModal
          modalState={importModalState}
          setModalState={setImportModalState}
          onImport={handleImportActions}
        />
        {showUnsavedModal && (
          <ConfirmationModal
            message={t('settings.tools.unsavedChanges')}
            modalState="ACTIVE"
            setModalState={(state) => setShowUnsavedModal(state === 'ACTIVE')}
            submitLabel={t('settings.tools.saveAndLeave')}
            handleSubmit={() => {
              let configToSave;
              if (tool.name === 'api_tool') {
                configToSave = tool.config;
              } else if (tool.name === 'mcp_tool') {
                configToSave = { ...tool.config } as any;
                const mcpConfig = tool.config as any;

                if (authKey.trim()) {
                  if (mcpConfig.auth_type === 'api_key') {
                    configToSave.api_key = authKey;
                  } else if (mcpConfig.auth_type === 'bearer') {
                    configToSave.encrypted_token = authKey;
                  } else if (mcpConfig.auth_type === 'basic') {
                    configToSave.password = authKey;
                  }
                }
              } else {
                configToSave = { token: authKey };
              }

              userService
                .updateTool(
                  {
                    id: tool.id,
                    name: tool.name,
                    displayName: tool.displayName,
                    customName: customName,
                    description: tool.description,
                    config: configToSave,
                    actions: 'actions' in tool ? tool.actions : [],
                    status: tool.status,
                  },
                  token,
                )
                .then(() => {
                  setShowUnsavedModal(false);
                  handleGoBack();
                });
            }}
            cancelLabel={t('settings.tools.leaveWithoutSaving')}
            handleCancel={() => {
              setShowUnsavedModal(false);
              handleGoBack();
            }}
          />
        )}
      </div>
    </div>
  );
}

function APIToolConfig({
  tool,
  setTool,
}: {
  tool: APIToolType;
  setTool: (tool: APIToolType) => void;
}) {
  const [apiTool, setApiTool] = React.useState<APIToolType>(tool);
  const { t } = useTranslation();
  const [actionToDelete, setActionToDelete] = React.useState<string | null>(
    null,
  );
  const [deleteModalState, setDeleteModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [searchQuery, setSearchQuery] = React.useState('');
  const [expandedActions, setExpandedActions] = React.useState<Set<string>>(
    new Set(),
  );

  const toggleActionExpand = (actionName: string) => {
    setExpandedActions((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(actionName)) {
        newSet.delete(actionName);
      } else {
        newSet.add(actionName);
      }
      return newSet;
    });
  };

  const filteredActions = React.useMemo(() => {
    if (!apiTool.config.actions) return [];
    const entries = Object.entries(apiTool.config.actions);
    const filtered = entries.filter(([actionName, action]) => {
      const query = searchQuery.toLowerCase();
      return (
        actionName.toLowerCase().includes(query) ||
        action.name.toLowerCase().includes(query) ||
        action.description?.toLowerCase().includes(query) ||
        action.url?.toLowerCase().includes(query)
      );
    });
    return filtered.sort((a, b) => a[0].localeCompare(b[0]));
  }, [apiTool.config.actions, searchQuery]);

  const handleDeleteActionClick = (actionName: string) => {
    setActionToDelete(actionName);
    setDeleteModalState('ACTIVE');
  };
  const handleConfirmedDelete = () => {
    if (actionToDelete) {
      setApiTool((prevApiTool) => {
        const { [actionToDelete]: deletedAction, ...remainingActions } =
          prevApiTool.config.actions;
        return {
          ...prevApiTool,
          config: {
            ...prevApiTool.config,
            actions: remainingActions,
          },
        };
      });
      setActionToDelete(null);
      setDeleteModalState('INACTIVE');
    }
  };

  const handleActionChange = (
    actionName: string,
    updatedAction: APIActionType,
  ) => {
    setApiTool((prevApiTool) => {
      const updatedActions = { ...prevApiTool.config.actions };
      updatedActions[actionName] = updatedAction;
      return {
        ...prevApiTool,
        config: { ...prevApiTool.config, actions: updatedActions },
      };
    });
  };

  const handleActionToggle = (actionName: string) => {
    setApiTool((prevApiTool) => {
      const updatedActions = { ...prevApiTool.config.actions };
      const updatedAction = { ...updatedActions[actionName] };
      updatedAction.active = !updatedAction.active;
      updatedActions[actionName] = updatedAction;
      return {
        ...prevApiTool,
        config: { ...prevApiTool.config, actions: updatedActions },
      };
    });
  };

  React.useEffect(() => {
    setApiTool(tool);
  }, [tool]);

  React.useEffect(() => {
    setTool(apiTool);
  }, [apiTool]);

  const getMethodColor = (method: string) => {
    return METHOD_COLORS[method.toUpperCase()] || METHOD_COLORS.GET;
  };

  return (
    <div className="scrollbar-overlay flex flex-col gap-4">
      <div className="relative">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('settings.tools.searchActions')}
          className="border-silver dark:border-silver/40 dark:bg-raisin-black w-full rounded-full border px-4 py-2 pl-10 text-sm outline-none focus:border-purple-500 dark:text-white dark:placeholder-gray-500"
        />
        <svg
          className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
      </div>

      {filteredActions.length === 0 && searchQuery && (
        <p className="py-4 text-center text-gray-500 dark:text-gray-400">
          {t('settings.tools.noActionsMatch')}
        </p>
      )}

      <div className="flex flex-col gap-4">
        {filteredActions.map(([actionName, action], actionIndex) => {
          const isExpanded = expandedActions.has(actionName);
          return (
            <div
              key={actionIndex}
              className="border-silver dark:border-silver/40 w-full rounded-xl border"
            >
              <div
                className={`border-silver dark:border-silver/40 flex cursor-pointer flex-wrap items-center justify-between ${isExpanded ? 'rounded-t-xl border-b' : 'rounded-xl'} bg-[#F9F9F9] px-4 py-3 dark:bg-[#28292D]`}
                onClick={() => toggleActionExpand(actionName)}
              >
                <div className="flex items-center gap-3">
                  <img
                    src={ChevronRight}
                    alt="expand"
                    className={`h-4 w-4 opacity-60 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
                  />
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${getMethodColor(action.method)}`}
                  >
                    {action.method}
                  </span>
                  <p className="text-eerie-black dark:text-bright-gray font-semibold">
                    {action.name}
                  </p>
                  {action.description && (
                    <p className="hidden truncate text-sm text-gray-500 md:block md:max-w-xs lg:max-w-md dark:text-gray-400">
                      {action.description}
                    </p>
                  )}
                </div>
                <div
                  className="flex items-center gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    onClick={() => handleDeleteActionClick(actionName)}
                    className="mr-2 flex h-6 w-6 items-center justify-center rounded-full"
                    title={t('convTile.delete')}
                  >
                    <img
                      src={Trash}
                      alt="delete"
                      className="h-4 w-4 opacity-40 transition-opacity hover:opacity-100"
                    />
                  </button>
                  <ToggleSwitch
                    checked={action.active}
                    onChange={() => handleActionToggle(actionName)}
                    size="small"
                    id={`actionToggle-${actionIndex}`}
                  />
                </div>
              </div>
              {isExpanded && (
                <>
                  <div className="mt-8 px-5">
                    <Input
                      type="text"
                      value={action.url}
                      onChange={(e) => {
                        setApiTool((prevApiTool) => {
                          const updatedActions = {
                            ...prevApiTool.config.actions,
                          };
                          const updatedAction = {
                            ...updatedActions[actionName],
                          };
                          updatedAction.url = e.target.value;
                          updatedActions[actionName] = updatedAction;
                          return {
                            ...prevApiTool,
                            config: {
                              ...prevApiTool.config,
                              actions: updatedActions,
                            },
                          };
                        });
                      }}
                      borderVariant="thin"
                      placeholder={t('settings.tools.urlPlaceholder')}
                    />
                  </div>
                  <div className="mt-4 px-5 py-2">
                    <div className="relative w-full">
                      <span className="text-gray-4000 dark:bg-raisin-black dark:text-silver absolute -top-2 left-5 z-10 bg-white px-2 text-xs">
                        {t('settings.tools.method')}
                      </span>
                      <Dropdown
                        options={[
                          'GET',
                          'POST',
                          'PUT',
                          'DELETE',
                          'PATCH',
                          'HEAD',
                          'OPTIONS',
                        ]}
                        selectedValue={action.method}
                        onSelect={(value: string) => {
                          setApiTool((prevApiTool) => {
                            const updatedActions = {
                              ...prevApiTool.config.actions,
                            };
                            const updatedAction = {
                              ...updatedActions[actionName],
                            };
                            updatedAction.method = value as
                              | 'GET'
                              | 'POST'
                              | 'PUT'
                              | 'DELETE'
                              | 'PATCH'
                              | 'HEAD'
                              | 'OPTIONS';
                            updatedActions[actionName] = updatedAction;
                            return {
                              ...prevApiTool,
                              config: {
                                ...prevApiTool.config,
                                actions: updatedActions,
                              },
                            };
                          });
                        }}
                        size="w-56"
                        rounded="3xl"
                        border="border"
                      />
                    </div>
                  </div>
                  <div className="mt-4 px-5 py-2">
                    <Input
                      type="text"
                      value={action.description}
                      onChange={(e) => {
                        setApiTool((prevApiTool) => {
                          const updatedActions = {
                            ...prevApiTool.config.actions,
                          };
                          const updatedAction = {
                            ...updatedActions[actionName],
                          };
                          updatedAction.description = e.target.value;
                          updatedActions[actionName] = updatedAction;
                          return {
                            ...prevApiTool,
                            config: {
                              ...prevApiTool.config,
                              actions: updatedActions,
                            },
                          };
                        });
                      }}
                      borderVariant="thin"
                      placeholder={t('settings.tools.descriptionPlaceholder')}
                    />
                  </div>
                  {(action.method === 'POST' ||
                    action.method === 'PUT' ||
                    action.method === 'PATCH' ||
                    action.method === 'HEAD' ||
                    action.method === 'OPTIONS') && (
                    <div className="mt-4 px-5 py-2">
                      <div className="relative w-full">
                        <span className="text-gray-4000 dark:bg-raisin-black dark:text-silver absolute -top-2 left-5 z-10 bg-white px-2 text-xs">
                          {t('settings.tools.bodyContentType')}
                        </span>
                        <Dropdown
                          options={[
                            'application/json',
                            'application/x-www-form-urlencoded',
                            'multipart/form-data',
                            'text/plain',
                            'application/xml',
                            'application/octet-stream',
                          ]}
                          selectedValue={
                            action.body_content_type || 'application/json'
                          }
                          onSelect={(value: string) => {
                            setApiTool((prevApiTool) => {
                              const updatedActions = {
                                ...prevApiTool.config.actions,
                              };
                              const updatedAction = {
                                ...updatedActions[actionName],
                              };
                              updatedAction.body_content_type = value as
                                | 'application/json'
                                | 'application/x-www-form-urlencoded'
                                | 'multipart/form-data'
                                | 'text/plain'
                                | 'application/xml'
                                | 'application/octet-stream';
                              updatedActions[actionName] = updatedAction;
                              return {
                                ...prevApiTool,
                                config: {
                                  ...prevApiTool.config,
                                  actions: updatedActions,
                                },
                              };
                            });
                          }}
                          size="w-56"
                          rounded="3xl"
                          border="border"
                        />
                      </div>
                      <p className="text-eerie-black dark:text-bright-gray mt-2 text-xs opacity-60">
                        {action.body_content_type === 'multipart/form-data' &&
                          'For APIs requiring multipart format. File uploads not supported through LLM.'}
                        {action.body_content_type ===
                          'application/octet-stream' &&
                          'Raw binary data, base64-encoded for transmission.'}
                        {action.body_content_type ===
                          'application/x-www-form-urlencoded' &&
                          'Standard form submission format. Best for legacy APIs and login forms.'}
                        {action.body_content_type === 'application/xml' &&
                          'Structured XML format. Use for SOAP and enterprise APIs.'}
                        {action.body_content_type === 'text/plain' &&
                          'Raw text data. Each field on a new line.'}
                        {(!action.body_content_type ||
                          action.body_content_type === 'application/json') &&
                          'Most common format. Use for modern REST APIs.'}
                      </p>
                    </div>
                  )}
                  <div className="mt-4 px-5 py-2">
                    <APIActionTable
                      apiAction={action}
                      handleActionChange={handleActionChange}
                    />
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* Confirmation Modal */}
      {deleteModalState === 'ACTIVE' && actionToDelete && (
        <ConfirmationModal
          message={t('settings.tools.deleteActionWarning', {
            name: actionToDelete,
          })}
          modalState={deleteModalState}
          setModalState={setDeleteModalState}
          handleSubmit={handleConfirmedDelete}
          handleCancel={() => {
            setDeleteModalState('INACTIVE');
            setActionToDelete(null);
          }}
          submitLabel={t('convTile.delete')}
          variant="danger"
        />
      )}
    </div>
  );
}

function APIActionTable({
  apiAction,
  handleActionChange,
}: {
  apiAction: APIActionType;
  handleActionChange: (
    actionName: string,
    updatedAction: APIActionType,
  ) => void;
}) {
  const { t } = useTranslation();

  const [action, setAction] = React.useState<APIActionType>(apiAction);
  const [newPropertyKey, setNewPropertyKey] = React.useState('');
  const [newPropertyType, setNewPropertyType] = React.useState<
    'string' | 'integer'
  >('string');
  const [addingPropertySection, setAddingPropertySection] = React.useState<
    'headers' | 'query_params' | 'body' | null
  >(null);
  const [editingPropertyKey, setEditingPropertyKey] = React.useState<{
    section: 'headers' | 'query_params' | 'body' | null;
    oldKey: string | null;
  }>({ section: null, oldKey: null });

  const handlePropertyChange = (
    section: 'headers' | 'query_params' | 'body',
    key: string,
    field: 'value' | 'description' | 'filled_by_llm',
    value: string | number | boolean,
  ) => {
    setAction((prevAction) => {
      const currentProperty = prevAction[section].properties[key];
      const updatedProperty: typeof currentProperty = {
        ...currentProperty,
        [field]: value,
        ...(field === 'filled_by_llm' && typeof value === 'boolean'
          ? { required: value }
          : {}),
      };
      const updatedProperties = {
        ...prevAction[section].properties,
        [key]: updatedProperty,
      };
      return {
        ...prevAction,
        [section]: {
          ...prevAction[section],
          properties: updatedProperties,
        },
      };
    });
  };

  const handleAddPropertyStart = (
    section: 'headers' | 'query_params' | 'body',
  ) => {
    setEditingPropertyKey({ section: null, oldKey: null });
    setAddingPropertySection(section);
    setNewPropertyKey('');
    setNewPropertyType('string');
  };
  const handleAddPropertyCancel = () => {
    setAddingPropertySection(null);
    setNewPropertyKey('');
    setNewPropertyType('string');
  };
  const handleAddProperty = () => {
    if (addingPropertySection && newPropertyKey.trim() !== '') {
      setAction((prevAction) => {
        const updatedProperties = {
          ...prevAction[addingPropertySection].properties,
          [newPropertyKey.trim()]: {
            type: newPropertyType,
            description: '',
            value: '',
            filled_by_llm: false,
            required: false,
          },
        };
        return {
          ...prevAction,
          [addingPropertySection]: {
            ...prevAction[addingPropertySection],
            properties: updatedProperties,
          },
        };
      });
      setNewPropertyKey('');
      setNewPropertyType('string');
      setAddingPropertySection(null);
    }
  };

  const handleRenamePropertyStart = (
    section: 'headers' | 'query_params' | 'body',
    oldKey: string,
  ) => {
    setAddingPropertySection(null);
    setEditingPropertyKey({ section, oldKey });
    setNewPropertyKey(oldKey);
  };
  const handleRenamePropertyCancel = () => {
    setEditingPropertyKey({ section: null, oldKey: null });
    setNewPropertyKey('');
    setNewPropertyType('string');
  };
  const handleRenameProperty = () => {
    if (
      editingPropertyKey.section &&
      editingPropertyKey.oldKey &&
      newPropertyKey.trim() !== '' &&
      newPropertyKey.trim() !== editingPropertyKey.oldKey
    ) {
      setAction((prevAction) => {
        const { section, oldKey } = editingPropertyKey;
        if (section && oldKey) {
          const { [oldKey]: oldProperty, ...restProperties } =
            prevAction[section].properties;
          const updatedProperties = {
            ...restProperties,
            [newPropertyKey.trim()]: oldProperty,
          };
          return {
            ...prevAction,
            [section]: {
              ...prevAction[section],
              properties: updatedProperties,
            },
          };
        }
        return prevAction;
      });
      setEditingPropertyKey({ section: null, oldKey: null });
      setNewPropertyKey('');
      setNewPropertyType('string');
    }
  };

  const handlePorpertyDelete = (
    section: 'headers' | 'query_params' | 'body',
    key: string,
  ) => {
    setAction((prevAction) => {
      const { [key]: deletedProperty, ...restProperties } =
        prevAction[section].properties;
      return {
        ...prevAction,
        [section]: {
          ...prevAction[section],
          properties: restProperties,
        },
      };
    });
  };

  const handlePropertyTypeChange = (
    section: 'headers' | 'query_params' | 'body',
    key: string,
    newType: 'string' | 'integer',
  ) => {
    setAction((prevAction) => {
      const updatedProperties = {
        ...prevAction[section].properties,
        [key]: {
          ...prevAction[section].properties[key],
          type: newType,
        },
      };
      return {
        ...prevAction,
        [section]: {
          ...prevAction[section],
          properties: updatedProperties,
        },
      };
    });
  };

  React.useEffect(() => {
    setAction(apiAction);
  }, [apiAction]);

  React.useEffect(() => {
    handleActionChange(action.name, action);
  }, [action]);
  const renderPropertiesTable = (
    section: 'headers' | 'query_params' | 'body',
  ) => {
    return (
      <>
        {Object.entries(action[section].properties).map(
          ([key, param], index) => (
            <tr key={index} className="font-normal text-nowrap">
              <td className="relative">
                {editingPropertyKey.section === section &&
                editingPropertyKey.oldKey === key ? (
                  <div className="flex flex-row items-center justify-between gap-2">
                    <input
                      value={newPropertyKey}
                      className="border-silver dark:border-silver/40 flex w-full min-w-[130.5px] items-start rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                      onChange={(e) => setNewPropertyKey(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRenameProperty();
                        }
                      }}
                    />
                    <div className="mt-1">
                      <button
                        onClick={handleRenameProperty}
                        className="mr-1 h-5 w-5"
                      >
                        <img
                          src={CircleCheck}
                          alt="check"
                          className="h-5 w-5"
                        />
                      </button>
                      <button
                        onClick={handleRenamePropertyCancel}
                        className="h-5 w-5"
                      >
                        <img src={CircleX} alt="cancel" className="h-5 w-5" />
                      </button>
                    </div>
                  </div>
                ) : (
                  <input
                    value={key}
                    className="border-silver dark:border-silver/40 flex w-full min-w-[175.5px] items-start rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                    onFocus={() => handleRenamePropertyStart(section, key)}
                    readOnly
                  />
                )}
              </td>
              <td>
                <select
                  value={param.type}
                  onChange={(e) =>
                    handlePropertyTypeChange(
                      section,
                      key,
                      e.target.value as 'string' | 'integer',
                    )
                  }
                  className="border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                >
                  <option value="string">string</option>
                  <option value="integer">integer</option>
                </select>
              </td>
              <td>
                <label className="ml-[10px] flex cursor-pointer items-start gap-4">
                  <div className="flex items-center">
                    <input
                      checked={param.filled_by_llm}
                      type="checkbox"
                      className="size-4 rounded-sm border-gray-300 bg-transparent"
                      onChange={(e) =>
                        handlePropertyChange(
                          section,
                          key,
                          'filled_by_llm',
                          e.target.checked,
                        )
                      }
                    />
                  </div>
                </label>
              </td>
              <td className="w-10">
                <input
                  value={param.description}
                  className="border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                  onChange={(e) =>
                    handlePropertyChange(
                      section,
                      key,
                      'description',
                      e.target.value,
                    )
                  }
                ></input>
              </td>
              <td>
                <input
                  value={param.value}
                  disabled={param.filled_by_llm}
                  onChange={(e) =>
                    handlePropertyChange(section, key, 'value', e.target.value)
                  }
                  className={`border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden ${param.filled_by_llm ? 'opacity-50' : ''}`}
                ></input>
              </td>
              <td
                style={{
                  width: '50px',
                  minWidth: '50px',
                  maxWidth: '50px',
                  padding: '0',
                }}
                className="border-silver dark:border-silver/40 border-b"
              >
                <button
                  onClick={() => handlePorpertyDelete(section, key)}
                  className="h-4 w-4 opacity-60 hover:opacity-100"
                >
                  <img src={Trash} alt="delete" className="h-4 w-4"></img>
                </button>
              </td>
            </tr>
          ),
        )}
        {addingPropertySection === section ? (
          <tr>
            <td>
              <input
                value={newPropertyKey}
                onChange={(e) => setNewPropertyKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleAddProperty();
                  }
                }}
                placeholder={t('settings.tools.propertyName')}
                className="border-silver dark:border-silver/40 flex w-full min-w-[130.5px] items-start rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
              />
            </td>
            <td>
              <select
                value={newPropertyType}
                onChange={(e) =>
                  setNewPropertyType(e.target.value as 'string' | 'integer')
                }
                className="border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
              >
                <option value="string">string</option>
                <option value="integer">integer</option>
              </select>
            </td>
            <td colSpan={3} className="text-right">
              <button
                onClick={handleAddProperty}
                className="bg-purple-30 hover:bg-violets-are-blue mr-1 rounded-full px-5 py-[4px] text-sm text-white"
              >
                {t('settings.tools.add')}
              </button>
              <button
                onClick={handleAddPropertyCancel}
                className="rounded-full border border-solid border-red-500 px-5 py-[4px] text-sm text-red-500 hover:bg-red-500 hover:text-white"
              >
                {t('settings.tools.cancel')}
              </button>
            </td>
            <td
              style={{
                width: '50px',
                minWidth: '50px',
                maxWidth: '50px',
                padding: '0',
              }}
            ></td>
          </tr>
        ) : (
          <tr>
            <td colSpan={5}>
              <button
                onClick={() => handleAddPropertyStart(section)}
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue flex items-start rounded-full border border-solid px-5 py-[4px] text-sm text-nowrap transition-colors hover:text-white"
              >
                {t('settings.tools.addNew')}
              </button>
            </td>
            <td
              style={{
                width: '50px',
                minWidth: '50px',
                maxWidth: '50px',
                padding: '0',
              }}
            ></td>
          </tr>
        )}
      </>
    );
  };

  const renderHeadersTable = () => {
    return (
      <>
        {Object.entries(action.headers.properties).map(
          ([key, param], index) => (
            <tr key={index} className="font-normal text-nowrap">
              <td className="relative">
                {editingPropertyKey.section === 'headers' &&
                editingPropertyKey.oldKey === key ? (
                  <div className="flex flex-row items-center justify-between gap-2">
                    <input
                      value={newPropertyKey}
                      className="border-silver dark:border-silver/40 flex w-full min-w-[130.5px] items-start rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                      onChange={(e) => setNewPropertyKey(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRenameProperty();
                        }
                      }}
                    />
                    <div className="mt-1">
                      <button
                        onClick={handleRenameProperty}
                        className="mr-1 h-5 w-5"
                      >
                        <img
                          src={CircleCheck}
                          alt="check"
                          className="h-5 w-5"
                        />
                      </button>
                      <button
                        onClick={handleRenamePropertyCancel}
                        className="h-5 w-5"
                      >
                        <img src={CircleX} alt="cancel" className="h-5 w-5" />
                      </button>
                    </div>
                  </div>
                ) : (
                  <input
                    value={key}
                    className="border-silver dark:border-silver/40 flex w-full min-w-[175.5px] items-start rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                    onFocus={() => handleRenamePropertyStart('headers', key)}
                    readOnly
                  />
                )}
              </td>
              <td>
                <input
                  value={param.value}
                  onChange={(e) =>
                    handlePropertyChange(
                      'headers',
                      key,
                      'value',
                      e.target.value,
                    )
                  }
                  placeholder="e.g., application/json"
                  className="border-silver dark:border-silver/40 w-full rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                />
              </td>
              <td>
                <input
                  value={param.description}
                  className="border-silver dark:border-silver/40 rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
                  onChange={(e) =>
                    handlePropertyChange(
                      'headers',
                      key,
                      'description',
                      e.target.value,
                    )
                  }
                />
              </td>
              <td
                style={{
                  width: '50px',
                  minWidth: '50px',
                  maxWidth: '50px',
                  padding: '0',
                }}
                className="border-silver dark:border-silver/40 border-b"
              >
                <button
                  onClick={() => handlePorpertyDelete('headers', key)}
                  className="h-4 w-4 opacity-60 hover:opacity-100"
                >
                  <img src={Trash} alt="delete" className="h-4 w-4"></img>
                </button>
              </td>
            </tr>
          ),
        )}
        {addingPropertySection === 'headers' ? (
          <tr>
            <td>
              <input
                value={newPropertyKey}
                onChange={(e) => setNewPropertyKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleAddProperty();
                  }
                }}
                placeholder={t('settings.tools.propertyName')}
                className="border-silver dark:border-silver/40 flex w-full min-w-[130.5px] items-start rounded-lg border bg-transparent px-2 py-1 text-sm outline-hidden"
              />
            </td>
            <td colSpan={2} className="text-right">
              <button
                onClick={handleAddProperty}
                className="bg-purple-30 hover:bg-violets-are-blue mr-1 rounded-full px-5 py-[4px] text-sm text-white"
              >
                {t('settings.tools.add')}
              </button>
              <button
                onClick={handleAddPropertyCancel}
                className="rounded-full border border-solid border-red-500 px-5 py-[4px] text-sm text-red-500 hover:bg-red-500 hover:text-white"
              >
                {t('settings.tools.cancel')}
              </button>
            </td>
            <td
              style={{
                width: '50px',
                minWidth: '50px',
                maxWidth: '50px',
                padding: '0',
              }}
            ></td>
          </tr>
        ) : (
          <tr>
            <td colSpan={3}>
              <button
                onClick={() => handleAddPropertyStart('headers')}
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue flex items-start rounded-full border border-solid px-5 py-[4px] text-sm text-nowrap transition-colors hover:text-white"
              >
                {t('settings.tools.addNew')}
              </button>
            </td>
            <td
              style={{
                width: '50px',
                minWidth: '50px',
                maxWidth: '50px',
                padding: '0',
              }}
            ></td>
          </tr>
        )}
      </>
    );
  };

  return (
    <div className="scrollbar-overlay flex flex-col gap-6">
      <div>
        <h3 className="text-eerie-black dark:text-bright-gray mb-1 text-base font-normal">
          {t('settings.tools.headers')}
        </h3>
        <table className="table-default">
          <thead>
            <tr>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.name')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.value')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.description')}
              </th>
              <th
                style={{
                  width: '50px',
                  minWidth: '50px',
                  maxWidth: '50px',
                  padding: '0',
                }}
              ></th>
            </tr>
          </thead>
          <tbody>{renderHeadersTable()}</tbody>
        </table>
      </div>
      <div>
        <h3 className="text-eerie-black dark:text-bright-gray mb-1 text-base font-normal">
          {t('settings.tools.queryParameters')}
        </h3>
        <table className="table-default">
          <thead>
            <tr>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.name')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.type')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.filledByLLM')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.description')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.value')}
              </th>
              <th
                style={{
                  width: '50px',
                  minWidth: '50px',
                  maxWidth: '50px',
                  padding: '0',
                }}
              ></th>
            </tr>
          </thead>
          <tbody>{renderPropertiesTable('query_params')}</tbody>
        </table>
      </div>
      <div className="mb-6">
        <h3 className="text-eerie-black dark:text-bright-gray mb-1 text-base font-normal">
          {t('settings.tools.body')}
        </h3>
        <table className="table-default">
          <thead>
            <tr>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.name')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.type')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.filledByLLM')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.description')}
              </th>
              <th className="text-eerie-black dark:text-bright-gray px-2 py-1 text-left text-sm font-normal">
                {t('settings.tools.value')}
              </th>
              <th
                style={{
                  width: '50px',
                  minWidth: '50px',
                  maxWidth: '50px',
                  padding: '0',
                }}
              ></th>
            </tr>
          </thead>
          <tbody>{renderPropertiesTable('body')}</tbody>
        </table>
      </div>
    </div>
  );
}
