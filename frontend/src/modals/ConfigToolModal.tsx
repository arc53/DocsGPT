import React from 'react';

import Exit from '../assets/exit.svg';
import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import { AvailableTool } from './types';
import userService from '../api/services/userService';

export default function ConfigToolModal({
  modalState,
  setModalState,
  tool,
  getUserTools,
}: {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  tool: AvailableTool | null;
  getUserTools: () => void;
}) {
  const [authKey, setAuthKey] = React.useState<string>('');

  const handleAddTool = (tool: AvailableTool) => {
    userService
      .createTool({
        name: tool.name,
        displayName: tool.displayName,
        description: tool.description,
        config: { token: authKey },
        actions: tool.actions,
        status: true,
      })
      .then(() => {
        setModalState('INACTIVE');
        getUserTools();
      });
  };
  return (
    <div
      className={`${
        modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } fixed top-0 left-0 z-30  h-screen w-screen  bg-gray-alpha flex items-center justify-center`}
    >
      <article className="flex w-11/12 sm:w-[512px] flex-col gap-4 rounded-2xl bg-white shadow-lg dark:bg-[#26272E]">
        <div className="relative">
          <button
            className="absolute top-3 right-4 m-2 w-3"
            onClick={() => {
              setModalState('INACTIVE');
            }}
          >
            <img className="filter dark:invert" src={Exit} />
          </button>
          <div className="p-6">
            <h2 className="font-semibold text-xl text-jet dark:text-bright-gray px-3">
              Tool Config
            </h2>
            <p className="mt-5 text-sm text-gray-600 dark:text-gray-400 px-3">
              Type: <span className="font-semibold">{tool?.name} </span>
            </p>
            <div className="mt-6 relative px-3">
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
            <div className="mt-8 flex flex-row-reverse gap-1 px-3">
              <button
                onClick={() => {
                  handleAddTool(tool as AvailableTool);
                }}
                className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-[#6F3FD1]"
              >
                Add Tool
              </button>
              <button
                onClick={() => {
                  setModalState('INACTIVE');
                }}
                className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </article>
    </div>
  );
}
