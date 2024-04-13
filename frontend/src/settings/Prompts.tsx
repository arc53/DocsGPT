import React from 'react';
import { PromptProps, ActiveState } from '../models/misc';
import Dropdown from '../components/Dropdown';
import PromptsModal from '../preferences/PromptsModal';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const Prompts: React.FC<PromptProps> = ({
  prompts,
  selectedPrompt,
  onSelectPrompt,
  setPrompts,
}) => {
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

  const handleAddPrompt = async () => {
    try {
      const response = await fetch(`${apiHost}/api/create_prompt`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: newPromptName,
          content: newPromptContent,
        }),
      });
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
      setNewPromptName(newPromptName);
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeletePrompt = (id: string) => {
    setPrompts(prompts.filter((prompt) => prompt.id !== id));
    fetch(`${apiHost}/api/delete_prompt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ id: id }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete prompt');
        }
        // get 1st prompt and set it as selected
        if (prompts.length > 0) {
          onSelectPrompt(prompts[0].name, prompts[0].id, prompts[0].type);
        }
      })
      .catch((error) => {
        console.error(error);
      });
  };

  const fetchPromptContent = async (id: string) => {
    console.log('fetching prompt content');
    try {
      const response = await fetch(
        `${apiHost}/api/get_single_prompt?id=${id}`,
        {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
        },
      );
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
    fetch(`${apiHost}/api/update_prompt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        id: id,
        name: editPromptName,
        content: editPromptContent,
      }),
    })
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
        <div className="mb-4 flex flex-row items-center gap-8">
          <div>
            <p className="font-semibold dark:text-bright-gray">Active Prompt</p>
            <Dropdown
              options={prompts}
              selectedValue={selectedPrompt.name}
              onSelect={handleSelectPrompt}
              size="w-56"
              rounded="3xl"
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
                fetchPromptContent(id);
                setCurrentPromptEdit({ id: id, name: name, type: type });
                setModalState('ACTIVE');
              }}
              onDelete={handleDeletePrompt}
            />
          </div>
          <button
            className="mt-[24px] rounded-3xl border-2 border-solid border-purple-30 px-5 py-3 text-purple-30 hover:bg-purple-30 hover:text-white"
            onClick={() => {
              setModalType('ADD');
              setModalState('ACTIVE');
            }}
          >
            Add new
          </button>
        </div>
      </div>
      <PromptsModal
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
};

export default Prompts;
