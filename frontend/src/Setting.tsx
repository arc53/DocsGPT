import React, { useState, useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Arrow2 from './assets/dropdown-arrow.svg';
import ArrowLeft from './assets/arrow-left.svg';
import ArrowRight from './assets/arrow-right.svg';
import Trash from './assets/trash.svg';
import {
  selectPrompt,
  setPrompt,
  selectSourceDocs,
} from './preferences/preferenceSlice';
import { Doc } from './preferences/preferenceApi';

type PromptProps = {
  prompts: { name: string; id: string; type: string }[];
  selectedPrompt: { name: string; id: string };
  onSelectPrompt: (name: string, id: string) => void;
  onAddPrompt: (name: string) => void;
  newPromptName: string;
  onNewPromptNameChange: (name: string) => void;
  isAddPromptModalOpen: boolean;
  onToggleAddPromptModal: () => void;
  onDeletePrompt: (name: string, id: string) => void;
};

const Setting: React.FC = () => {
  const tabs = ['General', 'Prompts', 'Documents'];
  //const tabs = ['General', 'Prompts', 'Documents', 'Widgets'];

  const [activeTab, setActiveTab] = useState('General');
  const [prompts, setPrompts] = useState<
    { name: string; id: string; type: string }[]
  >([]);
  const selectedPrompt = useSelector(selectPrompt);
  const [newPromptName, setNewPromptName] = useState('');
  const [isAddPromptModalOpen, setAddPromptModalOpen] = useState(false);
  const documents = useSelector(selectSourceDocs);
  const [isAddDocumentModalOpen, setAddDocumentModalOpen] = useState(false);
  const [newDocument, setNewDocument] = useState<Document>({
    name: '',
    vectorDate: '',
    vectorLocation: '',
  });
  const dispatch = useDispatch();

  const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
  const [widgetScreenshot, setWidgetScreenshot] = useState<File | null>(null);

  const updateWidgetScreenshot = (screenshot: File | null) => {
    setWidgetScreenshot(screenshot);
  };

  // Function to toggle the Add Document modal
  const toggleAddDocumentModal = () => {
    setAddDocumentModalOpen(!isAddDocumentModalOpen);
  };
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

  const onDeletePrompt = (name: string, id: string) => {
    setPrompts(prompts.filter((prompt) => prompt.id !== id));

    fetch(`${apiHost}/api/delete_prompt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      // send id in body only
      body: JSON.stringify({ id: id }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete prompt');
        }
      })
      .catch((error) => {
        console.error(error);
      });
  };

  const handleDeleteClick = (index: number, doc: Doc) => {
    const docPath = 'indexes/' + 'local' + '/' + doc.name;

    fetch(`${apiHost}/api/delete_old?path=${docPath}`, {
      method: 'GET',
    })
      .then(() => {
        // remove the image element from the DOM
        const imageElement = document.querySelector(
          `#img-${index}`,
        ) as HTMLElement;
        const parentElement = imageElement.parentNode as HTMLElement;
        parentElement.parentNode?.removeChild(parentElement);
      })
      .catch((error) => console.error(error));
  };

  return (
    <div className="p-4 pt-20 md:p-12">
      <p className="text-2xl font-bold text-eerie-black">Settings</p>
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
                  ? 'bg-purple-3000 text-purple-30'
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
      case 'Prompts':
        return (
          <Prompts
            prompts={prompts}
            selectedPrompt={selectedPrompt}
            onSelectPrompt={(name, id) =>
              dispatch(setPrompt({ name: name, id: id }))
            }
            onAddPrompt={addPrompt}
            newPromptName={''}
            onNewPromptNameChange={function (name: string): void {
              throw new Error('Function not implemented.');
            }}
            isAddPromptModalOpen={false}
            onToggleAddPromptModal={function (): void {
              throw new Error('Function not implemented.');
            }}
            onDeletePrompt={onDeletePrompt}
          />
        );
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
      default:
        return null;
    }
  }

  function addPrompt(name: string) {
    if (name) {
      setNewPromptName('');
      toggleAddPromptModal();
    }
  }

  function toggleAddPromptModal() {
    setAddPromptModalOpen(!isAddPromptModalOpen);
  }
};

const General: React.FC = () => {
  const themes = ['Light'];
  const languages = ['English'];
  const [selectedTheme, setSelectedTheme] = useState(themes[0]);
  const [selectedLanguage, setSelectedLanguage] = useState(languages[0]);

  return (
    <div className="mt-[59px]">
      <div className="mb-4">
        <p className="font-bold text-jet">Select Theme</p>
        <Dropdown
          options={themes}
          selectedValue={selectedTheme}
          onSelect={setSelectedTheme}
        />
      </div>
      <div>
        <p className="font-bold text-jet">Select Language</p>
        <Dropdown
          options={languages}
          selectedValue={selectedLanguage}
          onSelect={setSelectedLanguage}
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
  onAddPrompt,
  onDeletePrompt,
}) => {
  const [isAddPromptModalOpen, setAddPromptModalOpen] = useState(false);
  const [newPromptName, setNewPromptName] = useState('');

  const openAddPromptModal = () => {
    setAddPromptModalOpen(true);
  };

  const closeAddPromptModal = () => {
    setAddPromptModalOpen(false);
  };

  const handleSelectPrompt = (name: string) => {
    const selected = prompts.find((prompt) => prompt.name === name);
    if (selected) {
      onSelectPrompt(selected.name, selected.id);
    }
  };

  const handleDeletePrompt = (name: string) => {
    const selected = prompts.find((prompt) => prompt.name === name);
    if (selected) {
      onDeletePrompt(selected.name, selected.id);
    }
  };

  return (
    <div className="mt-[59px]">
      <div className="mb-4">
        <p className="font-bold text-jet">Active Prompt</p>
        <DropdownPrompt
          options={prompts}
          selectedValue={selectedPrompt.name}
          onSelect={handleSelectPrompt}
          showDelete={true}
          onDelete={handleDeletePrompt}
        />
      </div>
      {/* <div>
        <button
          onClick={openAddPromptModal}
          className="rounded-lg bg-purple-300 px-4 py-2 font-bold text-white transition-all hover:bg-purple-600"
        >
          Add New Prompt
        </button>
      </div> */}
      {isAddPromptModalOpen && (
        <AddPromptModal
          newPromptName={newPromptName}
          onNewPromptNameChange={setNewPromptName}
          onAddPrompt={() => {
            onAddPrompt(newPromptName);
            closeAddPromptModal();
          }}
          onClose={closeAddPromptModal}
        />
      )}
    </div>
  );
};

function DropdownPrompt({
  options,
  selectedValue,
  onSelect,
  showDelete,
  onDelete,
}: {
  options: { name: string; id: string; type: string }[];
  selectedValue: string;
  onSelect: (value: string) => void;
  showDelete?: boolean;
  onDelete: (value: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative mt-2 w-32">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full cursor-pointer items-center rounded-xl border-2 bg-white p-3"
      >
        <span className="flex-1 overflow-hidden text-ellipsis">
          {selectedValue}
        </span>
        <img
          src={Arrow2}
          alt="arrow"
          className={`transform ${
            isOpen ? 'rotate-180' : 'rotate-0'
          } h-3 w-3 transition-transform`}
        />
      </button>
      {isOpen && (
        <div className="absolute left-0 right-0 z-50 -mt-3 rounded-b-xl border-2 bg-white shadow-lg">
          {options.map((option, index) => (
            <div
              key={index}
              className="flex cursor-pointer items-center justify-between hover:bg-gray-100"
            >
              <span
                onClick={() => {
                  onSelect(option.name);
                  setIsOpen(false);
                }}
                className="ml-2 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3"
              >
                {option.name}
              </span>
              {showDelete && option.type === 'private' && (
                <button onClick={() => onDelete(option.name)} className="p-2">
                  {/* Icon or text for delete button */}
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Dropdown({
  options,
  selectedValue,
  onSelect,
  showDelete,
  onDelete,
}: {
  options: string[];
  selectedValue: string;
  onSelect: (value: string) => void;
  showDelete?: boolean; // optional
  onDelete?: (value: string) => void; // optional
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative mt-2 w-32">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full cursor-pointer items-center rounded-xl border-2 bg-white p-3"
      >
        <span className="flex-1 overflow-hidden text-ellipsis">
          {selectedValue}
        </span>
        <img
          src={Arrow2}
          alt="arrow"
          className={`transform ${
            isOpen ? 'rotate-180' : 'rotate-0'
          } h-3 w-3 transition-transform`}
        />
      </button>
      {isOpen && (
        <div className="absolute left-0 right-0 z-50 -mt-3 rounded-b-xl border-2 bg-white shadow-lg">
          {options.map((option, index) => (
            <div
              key={index}
              className="flex cursor-pointer items-center justify-between hover:bg-gray-100"
            >
              <span
                onClick={() => {
                  onSelect(option);
                  setIsOpen(false);
                }}
                className="ml-2 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3"
              >
                {option}
              </span>
              {showDelete && onDelete && (
                <button onClick={() => onDelete(option)} className="p-2">
                  {/* Icon or text for delete button */}
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

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
          className="mb-4 w-full rounded-3xl border-2 p-2"
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
        {/* <h2 className="text-xl font-semibold">Documents</h2> */}

        <div className="mt-[27px] overflow-x-auto">
          <table className="block w-full table-auto content-center justify-center text-center">
            <thead>
              <tr>
                <th className="border px-4 py-2">Document Name</th>
                <th className="border px-4 py-2">Vector Date</th>
                <th className="border px-4 py-2">Type</th>
                <th className="border px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {documents &&
                documents.map((document, index) => (
                  <tr key={index}>
                    <td className="border px-4 py-2">{document.name}</td>
                    <td className="border px-4 py-2">{document.date}</td>
                    <td className="border px-4 py-2">
                      {document.location === 'remote'
                        ? 'Pre-loaded'
                        : 'Private'}
                    </td>
                    <td className="border px-4 py-2">
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
