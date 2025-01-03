import React from 'react';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import Input from '../components/Input';
import { UserTool } from './types';

export default function ToolConfig({
  tool,
  setTool,
  handleGoBack,
}: {
  tool: UserTool;
  setTool: (tool: UserTool) => void;
  handleGoBack: () => void;
}) {
  const [authKey, setAuthKey] = React.useState<string>(
    tool.config?.token || '',
  );

  const handleCheckboxChange = (actionIndex: number, property: string) => {
    setTool({
      ...tool,
      actions: tool.actions.map((action, index) => {
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
      }),
    });
  };

  const handleSaveChanges = () => {
    userService
      .updateTool({
        id: tool.id,
        name: tool.name,
        displayName: tool.displayName,
        description: tool.description,
        config: { token: authKey },
        actions: tool.actions,
        status: tool.status,
      })
      .then(() => {
        handleGoBack();
      });
  };

  const handleDelete = () => {
    userService.deleteTool({ id: tool.id }).then(() => {
      handleGoBack();
    });
  };
  return (
    <div className="mt-8 flex flex-col gap-4">
      <div className="mb-4 flex items-center gap-3 text-eerie-black dark:text-bright-gray text-sm">
        <button
          className="text-sm text-gray-400 dark:text-gray-500 border dark:border-0 dark:bg-[#28292D] dark:hover:bg-[#2E2F34] p-3 rounded-full"
          onClick={handleGoBack}
        >
          <img src={ArrowLeft} alt="left-arrow" className="w-3 h-3" />
        </button>
        <p className="mt-px">Back to all tools</p>
      </div>
      <div>
        <p className="text-sm font-semibold text-eerie-black dark:text-bright-gray">
          Type
        </p>
        <p className="mt-1 text-base font-normal text-eerie-black dark:text-bright-gray font-sans">
          {tool.name}
        </p>
      </div>
      <div className="mt-1">
        {Object.keys(tool?.config).length !== 0 && (
          <p className="text-sm font-semibold text-eerie-black dark:text-bright-gray">
            Authentication
          </p>
        )}
        <div className="flex mt-4 flex-col sm:flex-row items-start sm:items-center gap-2">
          {Object.keys(tool?.config).length !== 0 && (
            <div className="relative w-96">
              <span className="absolute left-5 -top-2 bg-white px-2 text-xs text-gray-4000 dark:bg-[#26272E] dark:text-silver">
                API Key / Oauth
              </span>
              <Input
                type="text"
                value={authKey}
                onChange={(e) => setAuthKey(e.target.value)}
                borderVariant="thin"
                placeholder="Enter API Key / Oauth"
              ></Input>
            </div>
          )}
          <div className="flex items-center gap-2">
            <button
              className="rounded-full px-5 py-[10px] bg-purple-30 text-white hover:bg-[#6F3FD1] text-nowrap text-sm"
              onClick={handleSaveChanges}
            >
              Save changes
            </button>
            <button
              className="rounded-full px-5 py-[10px] border border-solid border-red-500 text-red-500 hover:bg-red-500 hover:text-white text-nowrap text-sm"
              onClick={handleDelete}
            >
              Delete
            </button>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <div className="mx-1 my-2 h-[0.8px] w-full rounded-full bg-[#C4C4C4]/40 lg:w-[95%] "></div>
        <p className="text-base font-semibold text-eerie-black dark:text-bright-gray">
          Actions
        </p>
        <div className="flex flex-col gap-10">
          {tool.actions.map((action, actionIndex) => {
            return (
              <div
                key={actionIndex}
                className="w-full border border-silver dark:border-silver/40 rounded-xl"
              >
                <div className="h-10 bg-[#F9F9F9] dark:bg-[#28292D] rounded-t-xl border-b border-silver dark:border-silver/40 flex items-center justify-between px-5 flex-wrap">
                  <p className="font-semibold text-eerie-black dark:text-bright-gray">
                    {action.name}
                  </p>
                  <label
                    htmlFor={`actionToggle-${actionIndex}`}
                    className="relative inline-block h-6 w-10 cursor-pointer rounded-full bg-gray-300 dark:bg-[#D2D5DA33]/20 transition [-webkit-tap-highlight-color:_transparent] has-[:checked]:bg-[#0C9D35CC] has-[:checked]:dark:bg-[#0C9D35CC]"
                  >
                    <input
                      type="checkbox"
                      id={`actionToggle-${actionIndex}`}
                      className="peer sr-only"
                      checked={action.active}
                      onChange={() => {
                        setTool({
                          ...tool,
                          actions: tool.actions.map((act, index) => {
                            if (index === actionIndex) {
                              return { ...act, active: !act.active };
                            }
                            return act;
                          }),
                        });
                      }}
                    />
                    <span className="absolute inset-y-0 start-0 m-[3px] size-[18px] rounded-full bg-white transition-all peer-checked:start-4"></span>
                  </label>
                </div>
                <div className="mt-5 relative px-5 w-full sm:w-96">
                  <Input
                    type="text"
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
                  ></Input>
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
                            <tr key={index} className="text-nowrap font-normal">
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
                                  className="bg-transparent border border-silver dark:border-silver/40 outline-none px-2 py-1 rounded-lg text-sm"
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
                                                  ...act.parameters.properties,
                                                  [param[0]]: {
                                                    ...act.parameters
                                                      .properties[param[0]],
                                                    description: e.target.value,
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
                                  className={`bg-transparent border border-silver dark:border-silver/40 outline-none px-2 py-1 rounded-lg text-sm ${param[1].filled_by_llm ? 'opacity-50' : ''}`}
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
                                                  ...act.parameters.properties,
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
      </div>
    </div>
  );
}
