import React, { useState } from 'react';
import Arrow2 from './assets/dropdown-arrow.svg';
import ArrowLeft from './assets/arrow-left.svg';
import ArrowRight from './assets/arrow-right.svg';

type PromptProps = {
  prompts: string[];
  selectedPrompt: string;
  onSelectPrompt: (prompt: string) => void;
  onAddPrompt: (name: string) => void;
  newPromptName: string;
  onNewPromptNameChange: (name: string) => void;
  isAddPromptModalOpen: boolean;
  onToggleAddPromptModal: () => void;
  onDeletePrompt: (name: string) => void;
};

const Setting: React.FC = () => {
  const tabs = ['General', 'Prompts', 'Documents', 'Widgets'];
  const [activeTab, setActiveTab] = useState('General');
  const [prompts, setPrompts] = useState<string[]>(['Prompt 1', 'Prompt 2']);
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [newPromptName, setNewPromptName] = useState('');
  const [isAddPromptModalOpen, setAddPromptModalOpen] = useState(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isAddDocumentModalOpen, setAddDocumentModalOpen] = useState(false);
  const [newDocument, setNewDocument] = useState<Document>({
    name: '',
    vectorDate: '',
    vectorLocation: '',
  });
  const onDeletePrompt = (name: string) => {
    setPrompts(prompts.filter((prompt) => prompt !== name));
    setSelectedPrompt(''); // Clear the selected prompt
  };

  // Function to add a new document
  const addDocument = () => {
    if (
      newDocument.name &&
      newDocument.vectorDate &&
      newDocument.vectorLocation
    ) {
      setDocuments([...documents, newDocument]);
      setNewDocument({
        name: '',
        vectorDate: '',
        vectorLocation: '',
      });
      toggleAddDocumentModal();
    }
  };

  // Function to toggle the Add Document modal
  const toggleAddDocumentModal = () => {
    setAddDocumentModalOpen(!isAddDocumentModalOpen);
  };

  const handleDeleteDocument = (index: number) => {
    const updatedDocuments = [...documents];
    updatedDocuments.splice(index, 1);
    setDocuments(updatedDocuments);
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

      {isAddDocumentModalOpen && (
        <AddDocumentModal
          newDocument={newDocument}
          onNewDocumentChange={setNewDocument}
          onAddDocument={addDocument}
          onClose={toggleAddDocumentModal}
        />
      )}
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
            onSelectPrompt={setSelectedPrompt}
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
            isAddDocumentModalOpen={isAddDocumentModalOpen}
            newDocument={newDocument}
            handleDeleteDocument={handleDeleteDocument}
            toggleAddDocumentModal={toggleAddDocumentModal}
          />
        );
      case 'Widgets':
        return <Widgets />;
      default:
        return null;
    }
  }

  function addPrompt(name: string) {
    if (name) {
      setPrompts([...prompts, name]);
      setNewPromptName('');
      toggleAddPromptModal();
    }
  }

  function toggleAddPromptModal() {
    setAddPromptModalOpen(!isAddPromptModalOpen);
  }
};

const General: React.FC = () => {
  const themes = ['Light', 'Dark'];
  const languages = ['English', 'French', 'Hindi'];
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

  const handleDeletePrompt = () => {
    if (selectedPrompt) {
      onDeletePrompt(selectedPrompt); // Remove the selected prompt
    }
  };

  return (
    <div className="mt-[59px]">
      <div className="mb-4">
        <p className="font-bold text-jet">Select Prompt</p>
        <Dropdown
          options={prompts}
          selectedValue={selectedPrompt}
          onSelect={onSelectPrompt}
        />
      </div>
      <div>
        <button
          onClick={openAddPromptModal}
          className="rounded-lg bg-purple-300 px-4 py-2 font-bold text-white transition-all hover:bg-purple-600"
        >
          Add New Prompt
        </button>
      </div>
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
      <div className="mt-4">
        <button
          onClick={handleDeletePrompt}
          className="rounded-lg bg-red-300 px-4 py-2 font-bold text-white transition-all hover:bg-red-600 hover:text-zinc-800"
        >
          Delete Prompt
        </button>
      </div>
    </div>
  );
};

function Dropdown({
  options,
  selectedValue,
  onSelect,
}: {
  options: string[];
  selectedValue: string;
  onSelect: (value: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative mt-2 h-[43.33px] w-[342px]">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full cursor-pointer items-center rounded-3xl border-2 bg-white p-3"
      >
        <span className="flex-1 overflow-hidden text-ellipsis">
          {selectedValue}
        </span>
        <img
          src={Arrow2}
          alt="arrow"
          className={`transform ${
            isOpen ? 'rotate-180' : 'rotate-0'
          } h-4 w-4 transition-transform`}
        />
      </button>
      {isOpen && (
        <div className="absolute left-0 right-0 top-12 z-50 mt-2 bg-white p-2 shadow-lg">
          {options.map((option, index) => (
            <div
              key={index}
              onClick={() => {
                onSelect(option);
                setIsOpen(false);
              }}
              className="flex cursor-pointer items-center justify-between border-b-2 py-3 hover:bg-gray-100"
            >
              <span className="flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap">
                {option}
              </span>
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
      <div className="rounded-lg bg-white p-4">
        <p className="mb-2 text-2xl font-bold text-jet">Add New Prompt</p>
        <input
          type="text"
          placeholder="Enter Prompt Name"
          value={newPromptName}
          onChange={(e) => onNewPromptNameChange(e.target.value)}
          className="mb-4 w-full rounded-lg border-2 p-2"
        />
        <button
          onClick={onAddPrompt}
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

type DocumentsProps = {
  documents: Document[];
  isAddDocumentModalOpen: boolean;
  newDocument: Document;
  handleDeleteDocument: (index: number) => void;
  toggleAddDocumentModal: () => void;
};

const Documents: React.FC<DocumentsProps> = ({
  documents,
  isAddDocumentModalOpen,
  newDocument,
  handleDeleteDocument,
  toggleAddDocumentModal,
}) => {
  return (
    <div className="mt-8">
      <div className="flex flex-col">
        {/* <h2 className="text-xl font-semibold">Documents</h2> */}

        <div className="mt-[27px] overflow-x-auto">
          <table className="block w-full table-auto content-center justify-center">
            <thead>
              <tr>
                <th className="border px-4 py-2">Document Name</th>
                <th className="border px-4 py-2">Vector Date</th>
                <th className="border px-4 py-2">Vector Location</th>
                <th className="border px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document, index) => (
                <tr key={index}>
                  <td className="border px-4 py-2">{document.name}</td>
                  <td className="border px-4 py-2">{document.vectorDate}</td>
                  <td className="border px-4 py-2">
                    {document.vectorLocation}
                  </td>
                  <td className="border px-4 py-2">
                    <button
                      className="rounded-lg bg-red-600 px-2 py-1 font-bold text-white hover:bg-red-800"
                      onClick={() => handleDeleteDocument(index)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          onClick={toggleAddDocumentModal}
          className="mt-10 w-32 rounded-lg bg-purple-300 px-4 py-2 font-bold text-white transition-all hover:bg-purple-600"
        >
          Add New
        </button>
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

const Widgets: React.FC = () => {
  return <div>This is widgets</div>;
};
