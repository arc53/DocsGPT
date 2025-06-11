import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import { ActiveState, PromptProps } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import PromptsModal from '../preferences/PromptsModal';
import ConfirmationModal from '../modals/ConfirmationModal';

export default function Prompts({
  prompts,
  selectedPrompt,
  onSelectPrompt,
  setPrompts,
}: PromptProps) {
  const handleSelectPrompt = ({
    name,
    id,
    type,
  }: {
    name: string;
    id: string;
    type: string;
  }) => {
    setEditPromptName(name);
    onSelectPrompt(name, id, type);
  };
  const token = useSelector(selectToken);
  const [newPromptName, setNewPromptName] = React.useState('');
  const [newPromptContent, setNewPromptContent] = React.useState('');
  const [editPromptName, setEditPromptName] = React.useState('');
  const [editPromptContent, setEditPromptContent] = React.useState('');
  const [currentPromptEdit, setCurrentPromptEdit] = React.useState({
    id: '',
    name: '',
    type: '',
  });
  const [modalType, setModalType] = React.useState<'ADD' | 'EDIT'>('ADD');
  const [modalState, setModalState] = React.useState<ActiveState>('INACTIVE');
  const { t } = useTranslation();

  const [promptToDelete, setPromptToDelete] = React.useState<{
    id: string;
    name: string;
  } | null>(null);

  const handleAddPrompt = async () => {
    try {
      const response = await userService.createPrompt(
        {
          name: newPromptName,
          content: newPromptContent,
        },
        token,
      );
      if (!response.ok) {
        throw new Error('Failed to add prompt');
      }
      const newPrompt = await response.json();
      if (setPrompts) {
        setPrompts([
          ...prompts,
          { name: newPromptName, id: newPrompt.id, type: 'private' },
        ]);
      }
      setModalState('INACTIVE');
      onSelectPrompt(newPromptName, newPrompt.id, newPromptContent);
      setNewPromptName('');
      setNewPromptContent('');
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeletePrompt = (id: string) => {
    const promptToRemove = prompts.find((prompt) => prompt.id === id);
    if (promptToRemove) {
      setPromptToDelete({ id, name: promptToRemove.name });
    }
  };

  const confirmDeletePrompt = () => {
    if (promptToDelete) {
      setPrompts(prompts.filter((prompt) => prompt.id !== promptToDelete.id));
      userService
        .deletePrompt({ id: promptToDelete.id }, token)
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to delete prompt');
          }
          if (prompts.length > 0) {
            const firstPrompt = prompts.find((p) => p.id !== promptToDelete.id);
            if (firstPrompt) {
              onSelectPrompt(
                firstPrompt.name,
                firstPrompt.id,
                firstPrompt.type,
              );
            }
          }
        })
        .catch((error) => {
          console.error(error);
        });
      setPromptToDelete(null);
    }
  };

  const handleFetchPromptContent = async (id: string) => {
    try {
      const response = await userService.getSinglePrompt(id, token);
      if (!response.ok) {
        throw new Error('Failed to fetch prompt content');
      }
      const promptContent = await response.json();
      setEditPromptContent(promptContent.content);
    } catch (error) {
      console.error(error);
    }
  };

  const handleSaveChanges = (id: string, type: string) => {
    userService
      .updatePrompt(
        {
          id: id,
          name: editPromptName,
          content: editPromptContent,
        },
        token,
      )
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to update prompt');
        }
        if (setPrompts) {
          const existingPromptIndex = prompts.findIndex(
            (prompt) => prompt.id === id,
          );
          if (existingPromptIndex === -1) {
            setPrompts([
              ...prompts,
              { name: editPromptName, id: id, type: type },
            ]);
          } else {
            const updatedPrompts = [...prompts];
            updatedPrompts[existingPromptIndex] = {
              name: editPromptName,
              id: id,
              type: type,
            };
            setPrompts(updatedPrompts);
          }
        }
        setModalState('INACTIVE');
        onSelectPrompt(editPromptName, id, type);
      })
      .catch((error) => {
        console.error(error);
      });
  };
  return (
    <>
      <div>
        <div className="flex flex-col gap-4">
          <p className="font-medium dark:text-bright-gray">
            {t('settings.general.prompt')}
          </p>
          <div className="flex flex-row items-baseline justify-start gap-6">
            <Dropdown
              options={prompts}
              selectedValue={selectedPrompt.name}
              onSelect={handleSelectPrompt}
              size="w-56"
              rounded="3xl"
              border="border"
              showEdit
              showDelete
              onEdit={({
                id,
                name,
                type,
              }: {
                id: string;
                name: string;
                type: string;
              }) => {
                setModalType('EDIT');
                setEditPromptName(name);
                handleFetchPromptContent(id);
                setCurrentPromptEdit({ id: id, name: name, type: type });
                setModalState('ACTIVE');
              }}
              onDelete={handleDeletePrompt}
            />

            <button
              className="h-10 w-20 rounded-3xl border border-solid border-violets-are-blue text-sm text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white"
              onClick={() => {
                setModalType('ADD');
                setModalState('ACTIVE');
              }}
            >
              {t('settings.general.add')}
            </button>
          </div>
        </div>
      </div>
      <PromptsModal
        existingPrompts={prompts}
        type={modalType}
        modalState={modalState}
        setModalState={setModalState}
        newPromptName={newPromptName}
        setNewPromptName={setNewPromptName}
        newPromptContent={newPromptContent}
        setNewPromptContent={setNewPromptContent}
        editPromptName={editPromptName}
        setEditPromptName={setEditPromptName}
        editPromptContent={editPromptContent}
        setEditPromptContent={setEditPromptContent}
        currentPromptEdit={currentPromptEdit}
        handleAddPrompt={handleAddPrompt}
        handleEditPrompt={handleSaveChanges}
      />
      {promptToDelete && (
        <ConfirmationModal
          message={t('modals.prompts.deleteConfirmation', {
            name: promptToDelete.name,
          })}
          modalState="ACTIVE"
          setModalState={() => setPromptToDelete(null)}
          submitLabel={t('modals.deleteConv.delete')}
          handleSubmit={confirmDeletePrompt}
          handleCancel={() => setPromptToDelete(null)}
          variant="danger"
        />
      )}
    </>
  );
}
