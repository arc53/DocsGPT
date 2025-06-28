import React from 'react';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import CircleCheck from '../assets/circle-check.svg';
import CircleX from '../assets/circle-x.svg';
import Trash from '../assets/trash.svg';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import ToggleSwitch from '../components/ToggleSwitch';
import AddActionModal from '../modals/AddActionModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { APIActionType, APIToolType, UserToolType } from './types';
import { useTranslation } from 'react-i18next';
import { areObjectsEqual } from '../utils/objectUtils';
import { useDarkTheme } from '../hooks';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';

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
  const [authKey, setAuthKey] = React.useState<string>(
    'token' in tool.config ? tool.config.token : '',
  );
  const [customName, setCustomName] = React.useState<string>(
    tool.customName || '',
  );
  const [actionModalState, setActionModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [initialState, setInitialState] = React.useState({
    customName: tool.customName || '',
    authKey: 'token' in tool.config ? tool.config.token : '',
    config: tool.config,
    actions: 'actions' in tool ? tool.actions : [],
  });
  const [hasUnsavedChanges, setHasUnsavedChanges] = React.useState(false);
  const [showUnsavedModal, setShowUnsavedModal] = React.useState(false);
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();

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
                return {
                  ...action,
                  parameters: {
                    ...action.parameters,
                    properties: {
                      ...action.parameters.properties,
                      [property]: {
                        ...action.parameters.properties[property],
                        filled_by_llm:
                          !action.parameters.properties[property].filled_by_llm,
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
    userService
      .updateTool(
        {
          id: tool.id,
          name: tool.name,
          displayName: tool.displayName,
          customName: customName,
          description: tool.description,
          config: tool.name === 'api_tool' ? tool.config : { token: authKey },
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
    };
    const toolCopy = tool as APIToolType;
    setTool({
      ...toolCopy,
      config: {
        ...toolCopy.config,
        actions: { ...toolCopy.config.actions, [actionName]: newAction },
      },
    });
  };
  return (
    <div className="scrollbar-thin mt-8 flex flex-col gap-4">
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
            {t('settings.tools.authentication')}
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
                  placeholder={t('modals.configTool.apiKeyPlaceholder')}
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
          {tool.name === 'api_tool' &&
            (!tool.config.actions ||
              Object.keys(tool.config.actions).length === 0) && (
              <button
                onClick={() => setActionModalState('ACTIVE')}
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
              >
                {t('settings.tools.addAction')}
              </button>
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
          <div className="flex flex-col gap-12">
            {'actions' in tool && tool.actions && tool.actions.length > 0 ? (
              tool.actions.map((action, actionIndex) => (
                <div
                  key={actionIndex}
                  className="border-silver dark:border-silver/40 w-full rounded-xl border"
                >
                  <div className="border-silver dark:border-silver/40 flex h-10 flex-wrap items-center justify-between rounded-t-xl border-b bg-[#F9F9F9] px-5 dark:bg-[#28292D]">
                    <p className="text-eerie-black dark:text-bright-gray font-semibold">
                      {action.name}
                    </p>
                    <ToggleSwitch
                      checked={action.active}
                      onChange={(checked) => {
                        setTool({
                          ...tool,
                          actions: tool.actions.map((act, index) => {
                            if (index === actionIndex) {
                              return { ...act, active: checked };
                            }
                            return act;
                          }),
                        });
                      }}
                      size="small"
                      id={`actionToggle-${actionIndex}`}
                    />
                  </div>
                  <div className="relative mt-5 w-full px-5">
                    <Input
                      type="text"
                      className="w-full"
                      placeholder={t('settings.tools.descriptionPlaceholder')}
                      value={action.description}
                      onChange={(e) => {
                        setTool({
                          ...tool,
                          actions: tool.actions.map((act, index) => {
                            if (index === actionIndex) {
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
                          <th>{t('settings.tools.fieldDescription')}</th>
                          <th>{t('settings.tools.value')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(action.parameters?.properties).map(
                          (param, index) => {
                            const uniqueKey = `${actionIndex}-${param[0]}`;
                            return (
                              <tr
                                key={index}
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
                                            actionIndex,
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
                                            if (index === actionIndex) {
                                              return {
                                                ...act,
                                                parameters: {
                                                  ...act.parameters,
                                                  properties: {
                                                    ...act.parameters
                                                      .properties,
                                                    [param[0]]: {
                                                      ...act.parameters
                                                        .properties[param[0]],
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
                                            if (index === actionIndex) {
                                              return {
                                                ...act,
                                                parameters: {
                                                  ...act.parameters,
                                                  properties: {
                                                    ...act.parameters
                                                      .properties,
                                                    [param[0]]: {
                                                      ...act.parameters
                                                        .properties[param[0]],
                                                      value: e.target.value,
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
                          },
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))
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
        {showUnsavedModal && (
          <ConfirmationModal
            message={t('settings.tools.unsavedChanges')}
            modalState="ACTIVE"
            setModalState={(state) => setShowUnsavedModal(state === 'ACTIVE')}
            submitLabel={t('settings.tools.saveAndLeave')}
            handleSubmit={() => {
              userService
                .updateTool(
                  {
                    id: tool.id,
                    name: tool.name,
                    displayName: tool.displayName,
                    customName: customName,
                    description: tool.description,
                    config:
                      tool.name === 'api_tool'
                        ? tool.config
                        : { token: authKey },
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
  return (
    <div className="scrollbar-thin flex flex-col gap-16">
      {/* Actions list */}
      {apiTool.config.actions &&
        Object.entries(apiTool.config.actions).map(
          ([actionName, action], actionIndex) => (
            <div
              key={actionIndex}
              className="border-silver dark:border-silver/40 w-full rounded-xl border"
            >
              <div className="border-silver dark:border-silver/40 flex h-10 flex-wrap items-center justify-between rounded-t-xl border-b bg-[#F9F9F9] px-5 dark:bg-[#28292D]">
                <p className="text-eerie-black dark:text-bright-gray font-semibold">
                  {action.name}
                </p>
                <div className="flex items-center gap-2">
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
                    options={['GET', 'POST', 'PUT', 'DELETE']}
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
                          | 'DELETE';
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
              <div className="mt-4 px-5 py-2">
                <APIActionTable
                  apiAction={action}
                  handleActionChange={handleActionChange}
                />
              </div>
            </div>
          ),
        )}

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
      const updatedProperties = {
        ...prevAction[section].properties,
        [key]: {
          ...prevAction[section].properties[key],
          [field]: value,
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

  const handleAddPropertyStart = (
    section: 'headers' | 'query_params' | 'body',
  ) => {
    setEditingPropertyKey({ section: null, oldKey: null });
    setAddingPropertySection(section);
    setNewPropertyKey('');
  };
  const handleAddPropertyCancel = () => {
    setAddingPropertySection(null);
    setNewPropertyKey('');
  };
  const handleAddProperty = () => {
    if (addingPropertySection && newPropertyKey.trim() !== '') {
      setAction((prevAction) => {
        const updatedProperties = {
          ...prevAction[addingPropertySection].properties,
          [newPropertyKey.trim()]: {
            type: 'string',
            description: '',
            value: '',
            filled_by_llm: false,
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
              <td>{param.type}</td>
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
            <td colSpan={4} className="text-right">
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
  return (
    <div className="scrollbar-thin flex flex-col gap-6">
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
          <tbody>{renderPropertiesTable('headers')}</tbody>
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
