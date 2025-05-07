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
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { APIActionType, APIToolType, UserToolType } from './types';
import { useTranslation } from 'react-i18next';

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
  const [actionModalState, setActionModalState] =
    React.useState<ActiveState>('INACTIVE');
  const { t } = useTranslation();
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
          description: tool.description,
          config: tool.name === 'api_tool' ? tool.config : { token: authKey },
          actions: 'actions' in tool ? tool.actions : [],
          status: tool.status,
        },
        token,
      )
      .then(() => {
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
    <div className="mt-8 flex flex-col gap-4">
      <div className="mb-4 flex items-center gap-3 text-sm text-eerie-black dark:text-bright-gray">
        <button
          className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={handleGoBack}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>
        <p className="mt-px">Back to all tools</p>
      </div>
      <div>
        <p className="text-sm font-semibold text-eerie-black dark:text-bright-gray">
          Type
        </p>
        <p className="mt-1 font-sans text-base font-normal text-eerie-black dark:text-bright-gray">
          {tool.name}
        </p>
      </div>
      <div className="mt-1">
        {Object.keys(tool?.config).length !== 0 && tool.name !== 'api_tool' && (
          <p className="text-sm font-semibold text-eerie-black dark:text-bright-gray">
            Authentication
          </p>
        )}
        <div className="mt-4 flex flex-col items-start gap-2 sm:flex-row sm:items-center">
          {Object.keys(tool?.config).length !== 0 &&
            tool.name !== 'api_tool' && (
              <div className="relative w-96">
                <Input
                  type="text"
                  value={authKey}
                  onChange={(e) => setAuthKey(e.target.value)}
                  borderVariant="thin"
                  placeholder={t('modals.configTool.apiKeyPlaceholder')}
                />
              </div>
            )}
          <div className="flex items-center gap-2">
            <button
              className="text-nowrap rounded-full bg-purple-30 px-5 py-[10px] text-sm text-white hover:bg-violets-are-blue"
              onClick={handleSaveChanges}
            >
              Save changes
            </button>
            <button
              className="text-nowrap rounded-full border border-solid border-red-500 px-5 py-[10px] text-sm text-red-500 hover:bg-red-500 hover:text-white"
              onClick={handleDelete}
            >
              Delete
            </button>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <div className="mx-1 my-2 h-[0.8px] w-full rounded-full bg-[#C4C4C4]/40 lg:w-[95%]"></div>
        <div className="flex w-full flex-row items-center justify-between gap-2">
          <p className="text-base font-semibold text-eerie-black dark:text-bright-gray">
            Actions
          </p>
          <button
            onClick={() => {
              setActionModalState('ACTIVE');
            }}
            className="rounded-full border border-solid border-violets-are-blue px-5 py-1 text-sm text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white"
          >
            Add action
          </button>
        </div>
        {tool.name === 'api_tool' ? (
          <APIToolConfig tool={tool as APIToolType} setTool={setTool} />
        ) : (
          <div className="flex flex-col gap-12">
            {'actions' in tool &&
              tool.actions.map((action, actionIndex) => {
                return (
                  <div
                    key={actionIndex}
                    className="w-full rounded-xl border border-silver dark:border-silver/40"
                  >
                    <div className="flex h-10 flex-wrap items-center justify-between rounded-t-xl border-b border-silver bg-[#F9F9F9] px-5 dark:border-silver/40 dark:bg-[#28292D]">
                      <p className="font-semibold text-eerie-black dark:text-bright-gray">
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
                    <div className="relative mt-5">
                      <Input
                        type="text"
                        className="ml-5 w-[97%]"
                        placeholder="Enter description"
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
                            <th>Field Name</th>
                            <th>Field Type</th>
                            <th>Filled by LLM</th>
                            <th>FIeld description</th>
                            <th>Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(action.parameters?.properties).map(
                            (param, index) => {
                              const uniqueKey = `${actionIndex}-${param[0]}`;
                              return (
                                <tr
                                  key={index}
                                  className="text-nowrap font-normal"
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
                                          className="size-4 rounded border-gray-300 bg-transparent"
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
                                      className="rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40"
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
                                      className={`rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40 ${param[1].filled_by_llm ? 'opacity-50' : ''}`}
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
                );
              })}
          </div>
        )}
        <AddActionModal
          modalState={actionModalState}
          setModalState={setActionModalState}
          handleSubmit={handleAddNewAction}
        />
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
    <div className="flex flex-col gap-16">
      {apiTool.config.actions &&
        Object.entries(apiTool.config.actions).map(
          ([actionName, action], actionIndex) => {
            return (
              <div
                key={actionIndex}
                className="w-full rounded-xl border border-silver dark:border-silver/40"
              >
                <div className="flex h-10 flex-wrap items-center justify-between rounded-t-xl border-b border-silver bg-[#F9F9F9] px-5 dark:border-silver/40 dark:bg-[#28292D]">
                  <p className="font-semibold text-eerie-black dark:text-bright-gray">
                    {action.name}
                  </p>
                  <ToggleSwitch
                    checked={action.active}
                    onChange={() => handleActionToggle(actionName)}
                    size="small"
                    id={`actionToggle-${actionIndex}`}
                  />
                </div>
                <div className="mt-8 px-5">
                  <div className="relative w-full">
                    <span className="absolute -top-2 left-5 z-10 bg-white px-2 text-xs text-gray-4000 dark:bg-raisin-black dark:text-silver">
                      URL
                    </span>
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
                      placeholder="Enter url"
                    ></Input>
                  </div>
                </div>
                <div className="mt-4 px-5 py-2">
                  <div className="relative w-full">
                    <span className="absolute -top-2 left-5 z-10 bg-white px-2 text-xs text-gray-4000 dark:bg-raisin-black dark:text-silver">
                      Method
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
                  <div className="relative w-full">
                    <span className="absolute -top-2 left-5 z-10 bg-white px-2 text-xs text-gray-4000 dark:bg-raisin-black dark:text-silver">
                      Description
                    </span>
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
                      placeholder="Enter description"
                    ></Input>
                  </div>
                </div>
                <div className="mt-4 px-5 py-2">
                  <APIActionTable
                    apiAction={action}
                    handleActionChange={handleActionChange}
                  />
                </div>
              </div>
            );
          },
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
            <tr key={index} className="text-nowrap font-normal">
              <td className="relative">
                {editingPropertyKey.section === section &&
                editingPropertyKey.oldKey === key ? (
                  <div className="flex flex-row items-center justify-between gap-2">
                    <input
                      value={newPropertyKey}
                      className="flex w-full min-w-[130.5px] items-start rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40"
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
                    className="flex w-full min-w-[175.5px] items-start rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40"
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
                      className="size-4 rounded border-gray-300 bg-transparent"
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
                  className="rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40"
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
                  className={`rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40 ${param.filled_by_llm ? 'opacity-50' : ''}`}
                ></input>
              </td>
              <td
                style={{
                  width: '50px',
                  minWidth: '50px',
                  maxWidth: '50px',
                  padding: '0',
                }}
                className="border-b border-silver dark:border-silver/40"
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
                placeholder="New property key"
                className="flex w-full min-w-[130.5px] items-start rounded-lg border border-silver bg-transparent px-2 py-1 text-sm outline-none dark:border-silver/40"
              />
            </td>
            <td colSpan={4} className="text-right">
              <button
                onClick={handleAddProperty}
                className="mr-1 rounded-full bg-purple-30 px-5 py-[4px] text-sm text-white hover:bg-violets-are-blue"
              >
                {' '}
                Add{' '}
              </button>
              <button
                onClick={handleAddPropertyCancel}
                className="rounded-full border border-solid border-red-500 px-5 py-[4px] text-sm text-red-500 hover:bg-red-500 hover:text-white"
              >
                {' '}
                Cancel{' '}
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
                className="flex items-start text-nowrap rounded-full border border-solid border-violets-are-blue px-5 py-[4px] text-sm text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white"
              >
                Add New Field
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
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="mb-1 text-base font-normal text-eerie-black dark:text-bright-gray">
          Headers
        </h3>
        <table className="table-default">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Filled by LLM</th>
              <th>Description</th>
              <th>Value</th>
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
        <h3 className="mb-1 text-base font-normal text-eerie-black dark:text-bright-gray">
          Query Parameters
        </h3>
        <table className="table-default">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Filled by LLM</th>
              <th>Description</th>
              <th>Value</th>
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
        <h3 className="mb-1 text-base font-normal text-eerie-black dark:text-bright-gray">
          Body
        </h3>
        <table className="table-default">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Filled by LLM</th>
              <th>Description</th>
              <th>Value</th>
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
