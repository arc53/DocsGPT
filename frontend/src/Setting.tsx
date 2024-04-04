import React, { useState, useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import ArrowLeft from './assets/arrow-left.svg';
import ArrowRight from './assets/arrow-right.svg';
import Exit from './assets/exit.svg';
import Trash from './assets/trash.svg';
import {
  selectPrompt,
  setPrompt,
  selectSourceDocs,
  setSourceDocs,
  setChunks,
  selectChunks,
} from './preferences/preferenceSlice';
import { Doc } from './preferences/preferenceApi';
import { useDarkTheme } from './hooks';
import Dropdown from './components/Dropdown';
import { ActiveState } from './models/misc';
import PromptsModal from './preferences/PromptsModal';
type PromptProps = {
  prompts: { name: string; id: string; type: string }[];
  selectedPrompt: { name: string; id: string; type: string };
  onSelectPrompt: (name: string, id: string, type: string) => void;
  setPrompts: (prompts: { name: string; id: string; type: string }[]) => void;
  apiHost: string;
};
const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

const Setting: React.FC = () => {
  const tabs = ['General', 'Documents', 'API Keys'];
  const [activeTab, setActiveTab] = useState('General');
  const documents = useSelector(selectSourceDocs);

  const dispatch = useDispatch();

  const [widgetScreenshot, setWidgetScreenshot] = useState<File | null>(null);

  const updateWidgetScreenshot = (screenshot: File | null) => {
    setWidgetScreenshot(screenshot);
  };

  const handleDeleteClick = (index: number, doc: Doc) => {
    const docPath = 'indexes/' + 'local' + '/' + doc.name;

    fetch(`${apiHost}/api/delete_old?path=${docPath}`, {
      method: 'GET',
    })
      .then((response) => {
        if (response.ok && documents) {
          const updatedDocuments = [
            ...documents.slice(0, index),
            ...documents.slice(index + 1),
          ];
          dispatch(setSourceDocs(updatedDocuments));
        }
      })
      .catch((error) => console.error(error));
  };

  return (
    <div className="wa p-4 pt-20 md:p-12">
      <p className="text-2xl font-bold text-eerie-black dark:text-bright-gray">
        Settings
      </p>
      <div className="mt-6 flex flex-row items-center space-x-4 overflow-x-auto md:space-x-8 ">
        <div className="md:hidden">
          <button
            onClick={() => scrollTabs(-1)}
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-purple-30 transition-all hover:bg-gray-100"
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-6 w-6" />
          </button>
        </div>
        <div className="flex flex-nowrap space-x-4 overflow-x-auto md:space-x-8">
          {tabs.map((tab, index) => (
            <button
              key={index}
              onClick={() => setActiveTab(tab)}
              className={`h-9 rounded-3xl px-4 font-bold ${
                activeTab === tab
                  ? 'bg-purple-3000 text-purple-30 dark:bg-dark-charcoal'
                  : 'text-gray-6000'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="md:hidden">
          <button
            onClick={() => scrollTabs(1)}
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-purple-30 hover:bg-gray-100"
          >
            <img src={ArrowRight} alt="right-arrow" className="h-6 w-6" />
          </button>
        </div>
      </div>
      {renderActiveTab()}

      {/* {activeTab === 'Widgets' && (
        <Widgets
          widgetScreenshot={widgetScreenshot}
          onWidgetScreenshotChange={updateWidgetScreenshot}
        />
      )} */}
    </div>
  );

  function scrollTabs(direction: number) {
    const container = document.querySelector('.flex-nowrap');
    if (container) {
      container.scrollLeft += direction * 100; // Adjust the scroll amount as needed
    }
  }

  function renderActiveTab() {
    switch (activeTab) {
      case 'General':
        return <General />;
      case 'Documents':
        return (
          <Documents
            documents={documents}
            handleDeleteDocument={handleDeleteClick}
          />
        );
      case 'Widgets':
        return (
          <Widgets
            widgetScreenshot={widgetScreenshot} // Add this line
            onWidgetScreenshotChange={updateWidgetScreenshot} // Add this line
          />
        );
      case 'API Keys':
        return <APIKeys />;
      default:
        return null;
    }
  }
};

const General: React.FC = () => {
  const themes = ['Light', 'Dark'];
  const languages = ['English'];
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const [prompts, setPrompts] = useState<
    { name: string; id: string; type: string }[]
  >([]);
  const selectedChunks = useSelector(selectChunks);
  const [isDarkTheme, toggleTheme] = useDarkTheme();
  const [selectedTheme, setSelectedTheme] = useState(
    isDarkTheme ? 'Dark' : 'Light',
  );
  const dispatch = useDispatch();
  const [selectedLanguage, setSelectedLanguage] = useState(languages[0]);
  const selectedPrompt = useSelector(selectPrompt);
  const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

  useEffect(() => {
    const fetchPrompts = async () => {
      try {
        const response = await fetch(`${apiHost}/api/get_prompts`);
        if (!response.ok) {
          throw new Error('Failed to fetch prompts');
        }
        const promptsData = await response.json();
        setPrompts(promptsData);
      } catch (error) {
        console.error(error);
      }
    };
    fetchPrompts();
  }, []);
  return (
    <div className="mt-[59px]">
      <div className="mb-4">
        <p className="font-bold text-jet dark:text-bright-gray">Select Theme</p>
        <Dropdown
          options={themes}
          selectedValue={selectedTheme}
          onSelect={(option: string) => {
            setSelectedTheme(option);
            option !== selectedTheme && toggleTheme();
          }}
          size="w-56"
          rounded="3xl"
        />
      </div>
      <div className="mb-4">
        <p className="font-bold text-jet dark:text-bright-gray">
          Select Language
        </p>
        <Dropdown
          options={languages}
          selectedValue={selectedLanguage}
          onSelect={setSelectedLanguage}
          size="w-56"
          rounded="3xl"
        />
      </div>
      <div className="mb-4">
        <p className="font-bold text-jet dark:text-bright-gray">
          Chunks processed per query
        </p>
        <Dropdown
          options={chunks}
          selectedValue={selectedChunks}
          onSelect={(value: string) => dispatch(setChunks(value))}
          size="w-56"
          rounded="3xl"
        />
      </div>
      <div>
        <Prompts
          prompts={prompts}
          selectedPrompt={selectedPrompt}
          onSelectPrompt={(name, id, type) =>
            dispatch(setPrompt({ name: name, id: id, type: type }))
          }
          setPrompts={setPrompts}
          apiHost={apiHost}
        />
      </div>
    </div>
  );
};

export default Setting;

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
  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptContent, setNewPromptContent] = useState('');
  const [editPromptName, setEditPromptName] = useState('');
  const [editPromptContent, setEditPromptContent] = useState('');
  const [currentPromptEdit, setCurrentPromptEdit] = useState({
    id: '',
    name: '',
    type: '',
  });
  const [modalType, setModalType] = useState<'ADD' | 'EDIT'>('ADD');
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');

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

type AddPromptModalProps = {
  newPromptName: string;
  onNewPromptNameChange: (name: string) => void;
  onAddPrompt: () => void;
  onClose: () => void;
};

const AddPromptModal: React.FC<AddPromptModalProps> = ({
  newPromptName,
  onNewPromptNameChange,
  onAddPrompt,
  onClose,
}) => {
  return (
    <div className="fixed top-0 left-0 flex h-screen w-screen items-center justify-center bg-gray-900 bg-opacity-50">
      <div className="rounded-3xl bg-white p-4">
        <p className="mb-2 text-2xl font-bold text-jet">Add New Prompt</p>
        <input
          type="text"
          placeholder="Enter Prompt Name"
          value={newPromptName}
          onChange={(e) => onNewPromptNameChange(e.target.value)}
          className="mb-4 w-full rounded-3xl border-2 p-2 dark:border-chinese-silver"
        />
        <button
          onClick={onAddPrompt}
          className="rounded-3xl bg-purple-300 px-4 py-2 font-bold text-white transition-all hover:bg-purple-600"
        >
          Save
        </button>
        <button
          onClick={onClose}
          className="mt-4 rounded-3xl px-4 py-2 font-bold text-red-500"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};
type DocumentsProps = {
  documents: Doc[] | null;
  handleDeleteDocument: (index: number, document: Doc) => void;
};

const Documents: React.FC<DocumentsProps> = ({
  documents,
  handleDeleteDocument,
}) => {
  return (
    <div className="mt-8">
      <div className="flex flex-col">
        <div className="mt-[27px] w-max overflow-x-auto rounded-xl border dark:border-chinese-silver">
          <table className="block w-full table-auto content-center justify-center text-center dark:text-bright-gray">
            <thead>
              <tr>
                <th className="border-r p-4 md:w-[244px]">Document Name</th>
                <th className="w-[244px] border-r px-4 py-2">Vector Date</th>
                <th className="w-[244px] border-r px-4 py-2">Type</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {documents &&
                documents.map((document, index) => (
                  <tr key={index}>
                    <td className="border-r border-t px-4 py-2">
                      {document.name}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.date}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.location === 'remote'
                        ? 'Pre-loaded'
                        : 'Private'}
                    </td>
                    <td className="border-t px-4 py-2">
                      {document.location !== 'remote' && (
                        <img
                          src={Trash}
                          alt="Delete"
                          className="h-4 w-4 cursor-pointer hover:opacity-50"
                          id={`img-${index}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            handleDeleteDocument(index, document);
                          }}
                        />
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {/* <button
          onClick={toggleAddDocumentModal}
          className="mt-10 w-32 rounded-lg bg-purple-300 px-4 py-2 font-bold text-white transition-all hover:bg-purple-600"
        >
          Add New
        </button> */}
      </div>

      {/* {isAddDocumentModalOpen && (
        <AddDocumentModal
          newDocument={newDocument}
          onNewDocumentChange={setNewDocument}
          onAddDocument={addDocument}
          onClose={toggleAddDocumentModal}
        />
      )} */}
    </div>
  );
};

type Document = {
  name: string;
  vectorDate: string;
  vectorLocation: string;
};

// Modal for adding a new document
type AddDocumentModalProps = {
  newDocument: Document;
  onNewDocumentChange: (document: Document) => void;
  onAddDocument: () => void;
  onClose: () => void;
};

const AddDocumentModal: React.FC<AddDocumentModalProps> = ({
  newDocument,
  onNewDocumentChange,
  onAddDocument,
  onClose,
}) => {
  return (
    <div className="fixed top-0 left-0 flex h-screen w-screen items-center justify-center bg-gray-900 bg-opacity-50">
      <div className="w-[50%] rounded-lg bg-white p-4">
        <p className="mb-2 text-2xl font-bold text-jet">Add New Document</p>
        <input
          type="text"
          placeholder="Document Name"
          value={newDocument.name}
          onChange={(e) =>
            onNewDocumentChange({ ...newDocument, name: e.target.value })
          }
          className="mb-4 w-full rounded-lg border-2 p-2"
        />
        <input
          type="text"
          placeholder="Vector Date"
          value={newDocument.vectorDate}
          onChange={(e) =>
            onNewDocumentChange({ ...newDocument, vectorDate: e.target.value })
          }
          className="mb-4 w-full rounded-lg border-2 p-2"
        />
        <input
          type="text"
          placeholder="Vector Location"
          value={newDocument.vectorLocation}
          onChange={(e) =>
            onNewDocumentChange({
              ...newDocument,
              vectorLocation: e.target.value,
            })
          }
          className="mb-4 w-full rounded-lg border-2 p-2"
        />
        <button
          onClick={onAddDocument}
          className="rounded-lg bg-purple-300 px-4 py-2 font-bold text-white transition-all hover:bg-purple-600"
        >
          Save
        </button>
        <button
          onClick={onClose}
          className="mt-4 rounded-lg px-4 py-2 font-bold text-red-500"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};
const APIKeys: React.FC = () => {
  const [isCreateModalOpen, setCreateModal] = useState(false);
  const [isSaveKeyModalOpen, setSaveKeyModal] = useState(false);
  const [newKey, setNewKey] = useState('');
  const [apiKeys, setApiKeys] = useState<
    { name: string; key: string; source: string; id: string }[]
  >([]);
  const handleDeleteKey = (id: string) => {
    fetch(`${apiHost}/api/delete_api_key`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ id }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete API Key');
        }
        return response.json();
      })
      .then((data) => {
        data.status === 'ok' &&
          setApiKeys((previous) => previous.filter((elem) => elem.id !== id));
      })
      .catch((error) => {
        console.error(error);
      });
  };
  useEffect(() => {
    fetchAPIKeys();
  }, []);
  const fetchAPIKeys = async () => {
    try {
      const response = await fetch(`${apiHost}/api/get_api_keys`);
      if (!response.ok) {
        throw new Error('Failed to fetch API Keys');
      }
      const apiKeys = await response.json();
      setApiKeys(apiKeys);
    } catch (error) {
      console.log(error);
    }
  };
  const createAPIKey = (payload: { name: string; source: string }) => {
    fetch(`${apiHost}/api/create_api_key`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to create API Key');
        }
        return response.json();
      })
      .then((data) => {
        setApiKeys([...apiKeys, data]);
        setCreateModal(false); //close the create key modal
        setNewKey(data.key);
        setSaveKeyModal(true); // render the newly created key
        fetchAPIKeys();
      })
      .catch((error) => {
        console.error(error);
      });
  };
  return (
    <div className="mt-8">
      <div className="flex w-full flex-col lg:w-max">
        <div className="flex justify-end">
          <button
            onClick={() => setCreateModal(true)}
            className="rounded-full bg-purple-30 px-4 py-3 text-sm text-white hover:bg-[#7E66B1]"
          >
            Create New
          </button>
        </div>
        {isCreateModalOpen && (
          <CreateAPIKeyModal
            close={() => setCreateModal(false)}
            createAPIKey={createAPIKey}
          />
        )}
        {isSaveKeyModalOpen && (
          <SaveAPIKeyModal
            apiKey={newKey}
            close={() => setSaveKeyModal(false)}
          />
        )}
        <div className="mt-[27px] w-full">
          <div className="w-full overflow-x-auto">
            <table className="block w-max table-auto content-center justify-center rounded-xl border text-center dark:border-chinese-silver dark:text-bright-gray">
              <thead>
                <tr>
                  <th className="border-r p-4 md:w-[244px]">Name</th>
                  <th className="w-[244px] border-r px-4 py-2">
                    Source document
                  </th>
                  <th className="w-[244px] border-r px-4 py-2">API Key</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {apiKeys?.map((element, index) => (
                  <tr key={index}>
                    <td className="border-r border-t p-4">{element.name}</td>
                    <td className="border-r border-t p-4">{element.source}</td>
                    <td className="border-r border-t p-4">{element.key}</td>
                    <td className="border-t p-4">
                      <img
                        src={Trash}
                        alt="Delete"
                        className="h-4 w-4 cursor-pointer hover:opacity-50"
                        id={`img-${index}`}
                        onClick={() => handleDeleteKey(element.id)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
type SaveAPIKeyModalProps = {
  apiKey: string;
  close: () => void;
};
const SaveAPIKeyModal: React.FC<SaveAPIKeyModalProps> = ({ apiKey, close }) => {
  const [isCopied, setIsCopied] = useState(false);
  const handleCopyKey = () => {
    navigator.clipboard.writeText(apiKey);
    setIsCopied(true);
  };
  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div className="relative w-11/12 rounded-md bg-white p-5 dark:bg-outer-space dark:text-bright-gray sm:w-[512px]">
        <button className="absolute top-4 right-4 w-4" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <h1 className="my-0 text-xl font-medium">Please save your Key</h1>
        <h3 className="text-sm font-normal text-outer-space">
          This is the only time your key will be shown.
        </h3>
        <div className="flex justify-between py-2">
          <div>
            <h2 className="text-base font-semibold">API Key</h2>
            <span className="text-sm font-normal leading-7 ">{apiKey}</span>
          </div>
          <button
            className="my-1 h-10 w-20 rounded-full border border-purple-30 p-2 text-sm text-purple-30 dark:border-purple-500 dark:text-purple-500"
            onClick={handleCopyKey}
          >
            {isCopied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <button
          onClick={close}
          className="rounded-full bg-philippine-yellow px-4 py-3 font-medium text-black hover:bg-[#E6B91A]"
        >
          I saved the Key
        </button>
      </div>
    </div>
  );
};

type CreateAPIKeyModalProps = {
  close: () => void;
  createAPIKey: (payload: { name: string; source: string }) => void;
};
const CreateAPIKeyModal: React.FC<CreateAPIKeyModalProps> = ({
  close,
  createAPIKey,
}) => {
  const [APIKeyName, setAPIKeyName] = useState<string>('');
  const [sourcePath, setSourcePath] = useState<{
    label: string;
    value: string;
  } | null>(null);
  const docs = useSelector(selectSourceDocs);
  const extractDocPaths = () =>
    docs
      ? docs
          .filter((doc) => doc.model === embeddingsName)
          .map((doc: Doc) => {
            let namePath = doc.name;
            if (doc.language === namePath) {
              namePath = '.project';
            }
            let docPath = 'default';
            if (doc.location === 'local') {
              docPath = 'local' + '/' + doc.name + '/';
            } else if (doc.location === 'remote') {
              docPath =
                doc.language +
                '/' +
                namePath +
                '/' +
                doc.version +
                '/' +
                doc.model +
                '/';
            }
            return {
              label: doc.name,
              value: docPath,
            };
          })
      : [];

  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div className="relative w-11/12 rounded-lg bg-white p-5 dark:bg-outer-space sm:w-[512px]">
        <button className="absolute top-2 right-2 m-2 w-4" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <span className="mb-4 text-xl font-bold text-jet dark:text-bright-gray">
          Create New API Key
        </span>
        <div className="relative my-4">
          <span className="absolute left-2 -top-2 bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
            API Key Name
          </span>
          <input
            type="text"
            className="h-10 w-full rounded-md border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
            value={APIKeyName}
            onChange={(e) => setAPIKeyName(e.target.value)}
          />
        </div>
        <div className="my-4">
          <Dropdown
            className="mt-2 w-full"
            placeholder="Select the source doc"
            selectedValue={sourcePath}
            onSelect={(selection: { label: string; value: string }) =>
              setSourcePath(selection)
            }
            options={extractDocPaths()}
          />
        </div>
        <button
          disabled={sourcePath === null || APIKeyName.length === 0}
          onClick={() =>
            sourcePath &&
            createAPIKey({ name: APIKeyName, source: sourcePath.value })
          }
          className="float-right my-4 rounded-full bg-purple-30 px-4 py-3 text-white disabled:opacity-50"
        >
          Create
        </button>
      </div>
    </div>
  );
};
const Widgets: React.FC<{
  widgetScreenshot: File | null;
  onWidgetScreenshotChange: (screenshot: File | null) => void;
}> = ({ widgetScreenshot, onWidgetScreenshotChange }) => {
  const widgetSources = ['Source 1', 'Source 2', 'Source 3'];
  const widgetMethods = ['Method 1', 'Method 2', 'Method 3'];
  const widgetTypes = ['Type 1', 'Type 2', 'Type 3'];

  const [selectedWidgetSource, setSelectedWidgetSource] = useState(
    widgetSources[0],
  );
  const [selectedWidgetMethod, setSelectedWidgetMethod] = useState(
    widgetMethods[0],
  );
  const [selectedWidgetType, setSelectedWidgetType] = useState(widgetTypes[0]);

  // const [widgetScreenshot, setWidgetScreenshot] = useState<File | null>(null);
  const [widgetCode, setWidgetCode] = useState<string>(''); // Your widget code state

  const handleScreenshotChange = (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = event.target.files;

    if (files && files.length > 0) {
      const selectedScreenshot = files[0];
      onWidgetScreenshotChange(selectedScreenshot); // Update the screenshot in the parent component
    }
  };

  const handleCopyToClipboard = () => {
    // Create a new textarea element to select the text
    const textArea = document.createElement('textarea');
    textArea.value = widgetCode;
    document.body.appendChild(textArea);

    // Select and copy the text
    textArea.select();
    document.execCommand('copy');

    // Clean up the textarea element
    document.body.removeChild(textArea);
  };

  return (
    <div>
      <div className="mt-[59px]">
        <p className="font-bold text-jet">Widget Source</p>
        <Dropdown
          options={widgetSources}
          selectedValue={selectedWidgetSource}
          onSelect={setSelectedWidgetSource}
        />
      </div>
      <div className="mt-5">
        <p className="font-bold text-jet">Widget Method</p>
        <Dropdown
          options={widgetMethods}
          selectedValue={selectedWidgetMethod}
          onSelect={setSelectedWidgetMethod}
        />
      </div>
      <div className="mt-5">
        <p className="font-bold text-jet">Widget Type</p>
        <Dropdown
          options={widgetTypes}
          selectedValue={selectedWidgetType}
          onSelect={setSelectedWidgetType}
        />
      </div>
      <div className="mt-6">
        <p className="font-bold text-jet">Widget Code Snippet</p>
        <textarea
          rows={4}
          value={widgetCode}
          onChange={(e) => setWidgetCode(e.target.value)}
          className="mt-3 w-full rounded-lg border-2 p-2"
        />
      </div>
      <div className="mt-1">
        <button
          onClick={handleCopyToClipboard}
          className="rounded-lg bg-blue-400 px-2 py-2 font-bold text-white transition-all hover:bg-blue-600"
        >
          Copy
        </button>
      </div>

      <div className="mt-4">
        <p className="text-lg font-semibold">Widget Screenshot</p>
        <input type="file" accept="image/*" onChange={handleScreenshotChange} />
      </div>

      {widgetScreenshot && (
        <div className="mt-4">
          <img
            src={URL.createObjectURL(widgetScreenshot)}
            alt="Widget Screenshot"
            className="max-w-full rounded-lg border border-gray-300"
          />
        </div>
      )}
    </div>
  );
};
