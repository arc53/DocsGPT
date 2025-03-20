import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import { ActiveState, PromptProps } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import PromptsModal from '../preferences/PromptsModal';

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
    setPrompts(prompts.filter((prompt) => prompt.id !== id));
    userService
      .deletePrompt({ id }, token)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete prompt');
        }
        if (prompts.length > 0) {
          onSelectPrompt(prompts[0].name, prompts[0].id, prompts[0].type);
        }
      })
      .catch((error) => {
        console.error(error);
      });
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
          <div className="flex flex-row justify-start items-baseline gap-6">
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
              className="rounded-3xl w-20 h-10 text-sm border border-solid border-violets-are-blue text-violets-are-blue transition-colors hover:text-white hover:bg-violets-are-blue"
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
    </>
  );
}
