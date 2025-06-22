import { ActiveState } from '../models/misc';
import Input from '../components/Input';
import React from 'react';
import { useTranslation } from 'react-i18next';
import WrapperModal from '../modals/WrapperModal';

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

  return (
    <div>
      <p className="text-jet dark:text-bright-gray mb-1 text-xl">
        {t('modals.prompts.addPrompt')}
      </p>
      <p className="text-sonic-silver mb-7 text-xs dark:text-[#7F7F82]">
        {t('modals.prompts.addDescription')}
      </p>
      <div>
        <Input
          placeholder={t('modals.prompts.promptName')}
          type="text"
          className="mb-4"
          value={newPromptName}
          onChange={(e) => setNewPromptName(e.target.value)}
          labelBgClassName="bg-white dark:bg-[#26272E]"
          borderVariant="thin"
        />
        <div className="relative top-[7px] left-3">
          <span className="text-silver dark:text-silver bg-white px-1 text-xs dark:bg-[#26272E]">
            {t('modals.prompts.promptText')}
          </span>
        </div>
        <label htmlFor="new-prompt-content" className="sr-only">
          {t('modals.prompts.promptText')}
        </label>
        <textarea
          id="new-prompt-content"
          className="border-silver dark:border-silver/40 h-56 w-full resize-none rounded-lg border-2 px-3 py-2 outline-hidden dark:bg-transparent dark:text-white"
          value={newPromptContent}
          onChange={(e) => setNewPromptContent(e.target.value)}
          aria-label="Prompt Text"
        ></textarea>
      </div>
      <div className="mt-6 flex flex-row-reverse">
        <button
          onClick={handleAddPrompt}
          className="bg-purple-30 hover:bg-violets-are-blue disabled:hover:bg-purple-30 rounded-3xl px-5 py-2 text-sm text-white transition-all"
          disabled={disableSave}
          title={
            disableSave && newPromptName ? t('modals.prompts.nameExists') : ''
          }
        >
          {t('modals.prompts.save')}
        </button>
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

  return (
    <div>
      <div className="">
        <p className="text-jet dark:text-bright-gray mb-1 text-xl">
          {t('modals.prompts.editPrompt')}
        </p>
        <p className="text-sonic-silver mb-7 text-xs dark:text-[#7F7F82]">
          {t('modals.prompts.editDescription')}
        </p>
        <div>
          <Input
            placeholder={t('modals.prompts.promptName')}
            type="text"
            className="mb-4"
            value={editPromptName}
            onChange={(e) => setEditPromptName(e.target.value)}
            labelBgClassName="bg-white dark:bg-charleston-green-2"
            borderVariant="thin"
          />
          <div className="relative top-[7px] left-3">
            <span className="text-silver dark:bg-charleston-green-2 dark:text-silver bg-white px-1 text-xs">
              {t('modals.prompts.promptText')}
            </span>
          </div>
          <label htmlFor="edit-prompt-content" className="sr-only">
            {t('modals.prompts.promptText')}
          </label>
          <textarea
            id="edit-prompt-content"
            className="border-silver dark:border-silver/40 h-56 w-full resize-none rounded-lg border-2 px-3 py-2 outline-hidden dark:bg-transparent dark:text-white"
            value={editPromptContent}
            onChange={(e) => setEditPromptContent(e.target.value)}
            aria-label="Prompt Text"
          ></textarea>
        </div>
        <div className="mt-6 flex flex-row-reverse gap-4">
          <button
            className={`bg-purple-30 hover:bg-violets-are-blue disabled:hover:bg-purple-30 rounded-3xl px-5 py-2 text-sm text-white transition-all ${
              currentPromptEdit.type === 'public'
                ? 'cursor-not-allowed opacity-50'
                : ''
            }`}
            onClick={() => {
              handleEditPrompt &&
                handleEditPrompt(currentPromptEdit.id, currentPromptEdit.type);
            }}
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
      className="mt-24 sm:w-[512px]"
    >
      {view}
    </WrapperModal>
  ) : null;
}
