import { ActiveState } from '../models/misc';
import Input from '../components/Input';
import { Link } from 'react-router-dom';

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import WrapperModal from '../modals/WrapperModal';
import Dropdown from '../components/Dropdown';
import BookIcon from '../assets/book.svg';
import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import { UserToolType } from '../settings/types';

// Custom hook for fetching tool variables
const useToolVariables = () => {
  const token = useSelector(selectToken);
  const [toolVariables, setToolVariables] = React.useState<
    { label: string; value: string }[]
  >([]);

  React.useEffect(() => {
    const fetchToolVariables = async () => {
      try {
        const response = await userService.getUserTools(token);
        const data = await response.json();

        if (data.success && data.tools) {
          const filteredActions: { label: string; value: string }[] = [];

          data.tools.forEach((tool: UserToolType) => {
            if (tool.actions && tool.status) {
              // Only include active tools
              tool.actions.forEach((action: any) => {
                if (action.active) {
                  const hasLLMParams =
                    action.parameters?.properties &&
                    Object.values(action.parameters.properties).some(
                      (param: any) => param.filled_by_llm !== false,
                    );

                  if (!hasLLMParams) {
                    filteredActions.push({
                      label: `${tool.displayName || tool.name}: ${action.name}`,
                      value: `tools.${tool.name}.${action.name}`,
                    });
                  }
                }
              });
            }
          });

          setToolVariables(filteredActions);
        }
      } catch (error) {
        console.error('Error fetching tool variables:', error);
      }
    };

    fetchToolVariables();
  }, [token]);

  return toolVariables;
};

function AddPrompt({
  setModalState,
  handleAddPrompt,
  newPromptName,
  setNewPromptName,
  newPromptContent,
  setNewPromptContent,
  disableSave,
}: {
  setModalState: (state: ActiveState) => void;
  handleAddPrompt?: () => void;
  newPromptName: string;
  setNewPromptName: (name: string) => void;
  newPromptContent: string;
  setNewPromptContent: (content: string) => void;
  disableSave: boolean;
}) {
  const { t } = useTranslation();
  const toolVariables = useToolVariables();

  return (
    <div>
      <p className="mb-1 text-xl font-semibold text-[#2B2B2B] dark:text-white">
        {t('modals.prompts.addPrompt')}
      </p>
      <p className="mb-6 text-sm text-[#6B6B6B] dark:text-[#9A9AA0]">
        {t('modals.prompts.addDescription')}
      </p>
      <div>
        <Input
          placeholder={t('modals.prompts.promptName')}
          type="text"
          className="mb-5"
          edgeRoundness="rounded-sm"
          value={newPromptName}
          onChange={(e) => setNewPromptName(e.target.value)}
          labelBgClassName="bg-white dark:bg-[#26272E]"
          borderVariant="thin"
        />

        <div className="mb-2 text-xs font-medium text-[#6B6B6B] dark:text-[#A0A0A5]">
          {t('modals.prompts.promptText')}
        </div>

        <div className="relative w-full">
          <textarea
            id="new-prompt-content"
            className="h-48 w-full rounded-lg border border-[#E0E0E0] bg-white px-3 py-2 text-sm text-gray-800 outline-none focus:border-purple-400 dark:border-[#3C3C44] dark:bg-[#26272E] dark:text-white"
            value={newPromptContent}
            onChange={(e) => setNewPromptContent(e.target.value)}
          />

          {!newPromptContent && (
            <div className="pointer-events-none absolute top-2 left-3 text-sm text-gray-400">
              {t('modals.prompts.placeholderText')}{' '}
              {/* <span className="text-green-500">{'{summaries}'}</span>
              <br />
              This is the code:
              <br />
              <span className="text-green-500">(code)</span> */}
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between gap-4">
        <p className="flex flex-col text-sm font-medium text-gray-700 dark:text-gray-300">
          <span className="font-bold">
            {t('modals.prompts.variablesLabel')}
          </span>
          <span className="text-xs text-[10px] font-medium text-gray-500">
            {t('modals.prompts.variablesDescription')}
          </span>
        </p>

        <div className="flex items-center gap-3">
          <Dropdown
            options={[{ label: 'Summaries', value: 'summaries' }]}
            selectedValue={'System Variables'}
            onSelect={(option) => {
              const textarea = document.getElementById(
                'new-prompt-content',
              ) as HTMLTextAreaElement;
              if (textarea) {
                const cursorPosition = textarea.selectionStart;
                const textBefore = newPromptContent.slice(0, cursorPosition);
                const textAfter = newPromptContent.slice(cursorPosition);
                const newText = textBefore + `{${option.value}}` + textAfter;
                setNewPromptContent(newText);

                setTimeout(() => {
                  textarea.focus();
                  textarea.setSelectionRange(
                    cursorPosition + option.value.length + 2,
                    cursorPosition + option.value.length + 2,
                  );
                }, 0);
              }
            }}
            placeholder="System Variables"
            size="w-[185px]"
            rounded="3xl"
            border="border"
            contentSize="text-[14px]"
          />

          <Dropdown
            options={toolVariables}
            selectedValue={'Tool Variables'}
            onSelect={(option) => {
              const textarea = document.getElementById(
                'new-prompt-content',
              ) as HTMLTextAreaElement;
              if (textarea) {
                const cursorPosition = textarea.selectionStart;
                const textBefore = newPromptContent.slice(0, cursorPosition);
                const textAfter = newPromptContent.slice(cursorPosition);
                const newText =
                  textBefore + `{{ ${option.value} }}` + textAfter;
                setNewPromptContent(newText);
                setTimeout(() => {
                  textarea.focus();
                  textarea.setSelectionRange(
                    cursorPosition + option.value.length + 6,
                    cursorPosition + option.value.length + 6,
                  );
                }, 0);
              }
            }}
            placeholder="Tool Variables"
            size="w-[171px]"
            rounded="3xl"
            border="border"
            contentSize="text-[14px]"
          />
        </div>
      </div>
      <div className="mt-4 flex justify-between text-[14px]">
        <div className="flex justify-center">
          <Link
            to="https://docs.docsgpt.cloud/Guides/Customising-prompts"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm font-medium text-[#6A4DF4] hover:underline"
          >
            <img
              src={BookIcon}
              alt=""
              className="flex h-4 w-3 flex-shrink-0 items-center justify-center"
              aria-hidden="true"
            />
            <span className="text-[14px] font-bold">
              {t('modals.prompts.learnAboutPrompts')}
            </span>
          </Link>
        </div>

        <div className="flex justify-end gap-4">
          <button
            onClick={() => setModalState('INACTIVE')}
            className="rounded-3xl border border-[#D9534F] px-5 py-2 text-sm font-medium text-[#D9534F] transition-all hover:bg-[#D9534F] hover:text-white"
          >
            {t('modals.prompts.cancel')}
          </button>

          <button
            onClick={handleAddPrompt}
            className="rounded-3xl bg-[#6A4DF4] px-6 py-2 text-sm font-medium text-white transition-all hover:bg-[#563DD1] disabled:opacity-50"
            disabled={disableSave}
          >
            {t('modals.prompts.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditPrompt({
  setModalState,
  handleEditPrompt,
  editPromptName,
  setEditPromptName,
  editPromptContent,
  setEditPromptContent,
  currentPromptEdit,
  disableSave,
}: {
  setModalState: (state: ActiveState) => void;
  handleEditPrompt?: (id: string, type: string) => void;
  editPromptName: string;
  setEditPromptName: (name: string) => void;
  editPromptContent: string;
  setEditPromptContent: (content: string) => void;
  currentPromptEdit: { name: string; id: string; type: string };
  disableSave: boolean;
}) {
  const { t } = useTranslation();
  const toolVariables = useToolVariables();

  return (
    <div>
      <p className="mb-1 text-xl font-semibold text-[#2B2B2B] dark:text-white">
        {t('modals.prompts.editPrompt')}
      </p>
      <p className="mb-6 text-sm text-[#6B6B6B] dark:text-[#9A9AA0]">
        {t('modals.prompts.editDescription')}
      </p>
      <div>
        <Input
          placeholder={t('modals.prompts.promptName')}
          type="text"
          className="mb-5"
          edgeRoundness="rounded-sm"
          value={editPromptName}
          onChange={(e) => setEditPromptName(e.target.value)}
          labelBgClassName="bg-white dark:bg-[#26272E]"
          borderVariant="thin"
        />

        <div className="mb-2 text-xs font-medium text-[#6B6B6B] dark:text-[#A0A0A5]">
          {t('modals.prompts.promptText')}
        </div>

        <div className="relative w-full">
          <textarea
            id="edit-prompt-content"
            className="h-48 w-full rounded-lg border border-[#E0E0E0] bg-white px-3 py-2 text-sm text-gray-800 outline-none focus:border-purple-400 dark:border-[#3C3C44] dark:bg-[#26272E] dark:text-white"
            value={editPromptContent}
            onChange={(e) => setEditPromptContent(e.target.value)}
          />

          {!editPromptContent && (
            <div className="pointer-events-none absolute top-2 left-3 text-sm text-gray-400">
              {t('modals.prompts.placeholderText')}
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between gap-4">
        <p className="flex flex-col text-sm font-medium text-gray-700 dark:text-gray-300">
          <span className="font-bold">
            {t('modals.prompts.variablesLabel')}
          </span>
          <span className="text-xs text-[10px] font-medium text-gray-500">
            {t('modals.prompts.variablesDescription')}
          </span>
        </p>

        <div className="flex items-center gap-3">
          <Dropdown
            options={[{ label: 'Summaries', value: 'summaries' }]}
            selectedValue={'System Variables'}
            onSelect={(option) => {
              const textarea = document.getElementById(
                'edit-prompt-content',
              ) as HTMLTextAreaElement;
              if (textarea) {
                const cursorPosition = textarea.selectionStart;
                const textBefore = editPromptContent.slice(0, cursorPosition);
                const textAfter = editPromptContent.slice(cursorPosition);
                const newText = textBefore + `{${option.value}}` + textAfter;
                setEditPromptContent(newText);

                setTimeout(() => {
                  textarea.focus();
                  textarea.setSelectionRange(
                    cursorPosition + option.value.length + 2,
                    cursorPosition + option.value.length + 2,
                  );
                }, 0);
              }
            }}
            placeholder="System Variables"
            size="w-[185px]"
            rounded="3xl"
            border="border"
            contentSize="text-[14px]"
          />

          <Dropdown
            options={toolVariables}
            selectedValue={'Tool Variables'}
            onSelect={(option) => {
              const textarea = document.getElementById(
                'edit-prompt-content',
              ) as HTMLTextAreaElement;
              if (textarea) {
                const cursorPosition = textarea.selectionStart;
                const textBefore = editPromptContent.slice(0, cursorPosition);
                const textAfter = editPromptContent.slice(cursorPosition);
                const newText =
                  textBefore + `{{ ${option.value} }}` + textAfter;
                setEditPromptContent(newText);
                setTimeout(() => {
                  textarea.focus();
                  textarea.setSelectionRange(
                    cursorPosition + option.value.length + 6,
                    cursorPosition + option.value.length + 6,
                  );
                }, 0);
              }
            }}
            placeholder="Tool Variables"
            size="w-[171px]"
            rounded="3xl"
            border="border"
            contentSize="text-[14px]"
          />
        </div>
      </div>
      <div className="mt-4 flex justify-between text-[14px]">
        <div className="flex justify-center">
          <Link
            to="https://docs.docsgpt.cloud/Guides/Customising-prompts"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm font-medium text-[#6A4DF4] hover:underline"
          >
            <img
              src={BookIcon}
              alt=""
              className="flex h-4 w-3 flex-shrink-0 items-center justify-center"
              aria-hidden="true"
            />
            <span className="text-[14px] font-bold">
              {t('modals.prompts.learnAboutPrompts')}
            </span>
          </Link>
        </div>

        <div className="flex justify-end gap-4">
          <button
            onClick={() => setModalState('INACTIVE')}
            className="rounded-3xl border border-[#D9534F] px-5 py-2 text-sm font-medium text-[#D9534F] transition-all hover:bg-[#D9534F] hover:text-white"
          >
            {t('modals.prompts.cancel')}
          </button>

          <button
            onClick={() => {
              handleEditPrompt &&
                handleEditPrompt(currentPromptEdit.id, currentPromptEdit.type);
            }}
            className="rounded-3xl bg-[#6A4DF4] px-6 py-2 text-sm font-medium text-white transition-all hover:bg-[#563DD1] disabled:opacity-50"
            disabled={currentPromptEdit.type === 'public' || disableSave}
            title={
              disableSave && editPromptName
                ? t('modals.prompts.nameExists')
                : ''
            }
          >
            {t('modals.prompts.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function PromptsModal({
  existingPrompts,
  modalState,
  setModalState,
  type,
  newPromptName,
  setNewPromptName,
  newPromptContent,
  setNewPromptContent,
  editPromptName,
  setEditPromptName,
  editPromptContent,
  setEditPromptContent,
  currentPromptEdit,
  handleAddPrompt,
  handleEditPrompt,
}: {
  existingPrompts: { name: string; id: string; type: string }[];
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  type: 'ADD' | 'EDIT';
  newPromptName: string;
  setNewPromptName: (name: string) => void;
  newPromptContent: string;
  setNewPromptContent: (content: string) => void;
  editPromptName: string;
  setEditPromptName: (name: string) => void;
  editPromptContent: string;
  setEditPromptContent: (content: string) => void;
  currentPromptEdit: {
    name: string;
    id: string;
    type: string;
    content?: string;
  };
  handleAddPrompt?: () => void;
  handleEditPrompt?: (id: string, type: string) => void;
}) {
  const [disableSave, setDisableSave] = React.useState(true);
  const handlePromptNameChange = (edit: boolean, newName: string) => {
    if (edit) {
      const nameExists = existingPrompts.find(
        (prompt) =>
          newName === prompt.name && prompt.id !== currentPromptEdit.id,
      );
      const nameValid = newName && !nameExists;
      const contentChanged = editPromptContent !== currentPromptEdit.content;

      setDisableSave(!(nameValid || contentChanged));
      setEditPromptName(newName);
    } else {
      const nameExists = existingPrompts.find(
        (prompt) => newName === prompt.name,
      );
      setDisableSave(!(newName && !nameExists));
      setNewPromptName(newName);
    }
  };

  const handleContentChange = (edit: boolean, newContent: string) => {
    if (edit) {
      const contentChanged = newContent !== currentPromptEdit.content;
      const nameValid =
        editPromptName &&
        !existingPrompts.find(
          (prompt) =>
            editPromptName === prompt.name &&
            prompt.id !== currentPromptEdit.id,
        );

      setDisableSave(!(nameValid || contentChanged));
      setEditPromptContent(newContent);
    } else {
      setNewPromptContent(newContent);
    }
  };

  let view;

  if (type === 'ADD') {
    view = (
      <AddPrompt
        setModalState={setModalState}
        handleAddPrompt={handleAddPrompt}
        newPromptName={newPromptName}
        setNewPromptName={handlePromptNameChange.bind(null, false)}
        newPromptContent={newPromptContent}
        setNewPromptContent={handleContentChange.bind(null, false)}
        disableSave={disableSave}
      />
    );
  } else if (type === 'EDIT') {
    view = (
      <EditPrompt
        setModalState={setModalState}
        handleEditPrompt={handleEditPrompt}
        editPromptName={editPromptName}
        setEditPromptName={handlePromptNameChange.bind(null, true)}
        editPromptContent={editPromptContent}
        setEditPromptContent={handleContentChange.bind(null, true)}
        currentPromptEdit={currentPromptEdit}
        disableSave={disableSave}
      />
    );
  } else {
    view = <></>;
  }

  return modalState === 'ACTIVE' ? (
    <WrapperModal
      close={() => {
        setModalState('INACTIVE');
        if (type === 'ADD') {
          setNewPromptName('');
          setNewPromptContent('');
        }
      }}
      className="mt-24 w-[650px] rounded-2xl bg-white px-8 py-6 dark:bg-[#1E1E2A]"
    >
      {view}
    </WrapperModal>
  ) : null;
}
