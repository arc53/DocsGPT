import isEqual from 'lodash/isEqual';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import SourceIcon from '../assets/source.svg';
import Dropdown from '../components/Dropdown';
import { FileUpload } from '../components/FileUpload';
import MultiSelectPopup, { OptionType } from '../components/MultiSelectPopup';
import Spinner from '../components/Spinner';
import AgentDetailsModal from '../modals/AgentDetailsModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, Prompt } from '../models/misc';
import {
  selectSelectedAgent,
  selectSourceDocs,
  selectToken,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import PromptsModal from '../preferences/PromptsModal';
import Prompts from '../settings/Prompts';
import { UserToolType } from '../settings/types';
import AgentPreview from './AgentPreview';
import { Agent } from './types';

const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

export default function NewAgent({ mode }: { mode: 'new' | 'edit' | 'draft' }) {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const { agentId } = useParams();

  const token = useSelector(selectToken);
  const sourceDocs = useSelector(selectSourceDocs);
  const selectedAgent = useSelector(selectSelectedAgent);

  const [effectiveMode, setEffectiveMode] = useState(mode);
  const [agent, setAgent] = useState<Agent>({
    id: agentId || '',
    name: '',
    description: '',
    image: '',
    source: '',
    chunks: '',
    retriever: '',
    prompt_id: 'default',
    tools: [],
    agent_type: '',
    status: '',
  });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [prompts, setPrompts] = useState<
    { name: string; id: string; type: string }[]
  >([]);
  const [userTools, setUserTools] = useState<OptionType[]>([]);
  const [isSourcePopupOpen, setIsSourcePopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [selectedSourceIds, setSelectedSourceIds] = useState<
    Set<string | number>
  >(new Set());
  const [selectedToolIds, setSelectedToolIds] = useState<Set<string | number>>(
    new Set(),
  );
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [agentDetails, setAgentDetails] = useState<ActiveState>('INACTIVE');
  const [addPromptModal, setAddPromptModal] = useState<ActiveState>('INACTIVE');
  const [hasChanges, setHasChanges] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);

  const initialAgentRef = useRef<Agent | null>(null);
  const sourceAnchorButtonRef = useRef<HTMLButtonElement>(null);
  const toolAnchorButtonRef = useRef<HTMLButtonElement>(null);

  const modeConfig = {
    new: {
      heading: 'New Agent',
      buttonText: 'Publish',
      showDelete: false,
      showSaveDraft: true,
      showLogs: false,
      showAccessDetails: false,
      trackChanges: false,
    },
    edit: {
      heading: 'Edit Agent',
      buttonText: 'Save',
      showDelete: true,
      showSaveDraft: false,
      showLogs: true,
      showAccessDetails: true,
      trackChanges: true,
    },
    draft: {
      heading: 'New Agent (Draft)',
      buttonText: 'Publish',
      showDelete: true,
      showSaveDraft: true,
      showLogs: false,
      showAccessDetails: false,
      trackChanges: false,
    },
  };
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const agentTypes = [
    { label: 'Classic', value: 'classic' },
    { label: 'ReAct', value: 'react' },
  ];

  const isPublishable = () => {
    return (
      agent.name && agent.description && agent.prompt_id && agent.agent_type
    );
  };

  const handleUpload = useCallback((files: File[]) => {
    if (files && files.length > 0) {
      const file = files[0];
      setImageFile(file);
    }
  }, []);

  const handleCancel = () => {
    if (selectedAgent) dispatch(setSelectedAgent(null));
    navigate('/agents');
  };

  const handleDelete = async (agentId: string) => {
    const response = await userService.deleteAgent(agentId, token);
    if (!response.ok) throw new Error('Failed to delete agent');
    navigate('/agents');
  };

  const handleSaveDraft = async () => {
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);
    formData.append('source', agent.source);
    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'draft');

    if (imageFile) formData.append('image', imageFile);

    if (agent.tools && agent.tools.length > 0)
      formData.append('tools', JSON.stringify(agent.tools));
    else formData.append('tools', '[]');

    try {
      setDraftLoading(true);
      const response =
        effectiveMode === 'new'
          ? await userService.createAgent(formData, token)
          : await userService.updateAgent(agent.id || '', formData, token);
      if (!response.ok) throw new Error('Failed to create agent draft');
      const data = await response.json();

      const updatedAgent = {
        ...agent,
        id: data.id || agent.id,
        image: data.image || agent.image,
      };
      setAgent(updatedAgent);

      if (effectiveMode === 'new') setEffectiveMode('draft');
    } catch (error) {
      console.error('Error saving draft:', error);
      throw new Error('Failed to save draft');
    } finally {
      setDraftLoading(false);
    }
  };

  const handlePublish = async () => {
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);
    formData.append('source', agent.source);
    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'published');

    if (imageFile) formData.append('image', imageFile);
    if (agent.tools && agent.tools.length > 0)
      formData.append('tools', JSON.stringify(agent.tools));
    else formData.append('tools', '[]');

    try {
      setPublishLoading(true);
      const response =
        effectiveMode === 'new'
          ? await userService.createAgent(formData, token)
          : await userService.updateAgent(agent.id || '', formData, token);
      if (!response.ok) throw new Error('Failed to publish agent');
      const data = await response.json();

      const updatedAgent = {
        ...agent,
        id: data.id || agent.id,
        key: data.key || agent.key,
        status: 'published',
        image: data.image || agent.image,
      };
      setAgent(updatedAgent);
      initialAgentRef.current = updatedAgent;

      if (effectiveMode === 'new' || effectiveMode === 'draft') {
        setEffectiveMode('edit');
        setAgentDetails('ACTIVE');
      }
      setImageFile(null);
    } catch (error) {
      console.error('Error publishing agent:', error);
      throw new Error('Failed to publish agent');
    } finally {
      setPublishLoading(false);
    }
  };

  useEffect(() => {
    const getTools = async () => {
      const response = await userService.getUserTools(token);
      if (!response.ok) throw new Error('Failed to fetch tools');
      const data = await response.json();
      const tools: OptionType[] = data.tools.map((tool: UserToolType) => ({
        id: tool.id,
        label: tool.displayName,
        icon: `/toolIcons/tool_${tool.name}.svg`,
      }));
      setUserTools(tools);
    };
    const getPrompts = async () => {
      const response = await userService.getPrompts(token);
      if (!response.ok) {
        throw new Error('Failed to fetch prompts');
      }
      const data = await response.json();
      setPrompts(data);
    };
    getTools();
    getPrompts();
  }, [token]);

  useEffect(() => {
    if ((mode === 'edit' || mode === 'draft') && agentId) {
      const getAgent = async () => {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) {
          navigate('/agents');
          throw new Error('Failed to fetch agent');
        }
        const data = await response.json();
        if (data.source) setSelectedSourceIds(new Set([data.source]));
        else if (data.retriever)
          setSelectedSourceIds(new Set([data.retriever]));
        if (data.tools) setSelectedToolIds(new Set(data.tools));
        if (data.status === 'draft') setEffectiveMode('draft');
        setAgent(data);
        initialAgentRef.current = data;
      };
      getAgent();
    }
  }, [agentId, mode, token]);

  useEffect(() => {
    const selectedSource = Array.from(selectedSourceIds).map((id) =>
      sourceDocs?.find(
        (source) =>
          source.id === id || source.retriever === id || source.name === id,
      ),
    );
    if (selectedSource[0]?.model === embeddingsName) {
      if (selectedSource[0] && 'id' in selectedSource[0]) {
        setAgent((prev) => ({
          ...prev,
          source: selectedSource[0]?.id || 'default',
          retriever: '',
        }));
      } else
        setAgent((prev) => ({
          ...prev,
          source: '',
          retriever: selectedSource[0]?.retriever || 'classic',
        }));
    }
  }, [selectedSourceIds]);

  useEffect(() => {
    const selectedTool = Array.from(selectedToolIds).map((id) =>
      userTools.find((tool) => tool.id === id),
    );
    setAgent((prev) => ({
      ...prev,
      tools: selectedTool
        .map((tool) => tool?.id)
        .filter((id): id is string => typeof id === 'string'),
    }));
  }, [selectedToolIds]);

  useEffect(() => {
    if (isPublishable()) dispatch(setSelectedAgent(agent));

    if (!modeConfig[effectiveMode].trackChanges) {
      setHasChanges(true);
      return;
    }
    if (!initialAgentRef.current) {
      setHasChanges(false);
      return;
    }
    const isChanged =
      !isEqual(agent, initialAgentRef.current) || imageFile !== null;
    setHasChanges(isChanged);
  }, [agent, dispatch, effectiveMode, imageFile]);
  return (
    <div className="p-4 md:p-12">
      <div className="flex items-center gap-3 px-4">
        <button
          className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={handleCancel}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>
        <p className="text-eerie-black dark:text-bright-gray mt-px text-sm font-semibold">
          Back to all agents
        </p>
      </div>
      <div className="mt-5 flex w-full flex-wrap items-center justify-between gap-2 px-4">
        <h1 className="text-eerie-black m-0 text-[40px] font-bold dark:text-white">
          {modeConfig[effectiveMode].heading}
        </h1>
        <div className="flex flex-wrap items-center gap-1">
          <button
            className="text-purple-30 dark:text-light-gray mr-4 rounded-3xl py-2 text-sm font-medium dark:bg-transparent"
            onClick={handleCancel}
          >
            Cancel
          </button>
          {modeConfig[effectiveMode].showDelete && agent.id && (
            <button
              className="group border-red-2000 text-red-2000 hover:bg-red-2000 flex items-center gap-2 rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={() => setDeleteConfirmation('ACTIVE')}
            >
              <span className="block h-4 w-4 bg-[url('/src/assets/red-trash.svg')] bg-contain bg-center bg-no-repeat transition-all group-hover:bg-[url('/src/assets/white-trash.svg')]" />
              Delete
            </button>
          )}
          {modeConfig[effectiveMode].showSaveDraft && (
            <button
              className="hover:bg-vi</button>olets-are-blue border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue w-28 rounded-3xl border border-solid py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={handleSaveDraft}
            >
              <span className="flex items-center justify-center transition-all duration-200">
                {draftLoading ? (
                  <Spinner size="small" color="#976af3" />
                ) : (
                  'Save Draft'
                )}
              </span>
            </button>
          )}
          {modeConfig[effectiveMode].showAccessDetails && (
            <button
              className="group border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue flex items-center gap-2 rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={() => navigate(`/agents/logs/${agent.id}`)}
            >
              <span className="block h-5 w-5 bg-[url('/src/assets/monitoring-purple.svg')] bg-contain bg-center bg-no-repeat transition-all group-hover:bg-[url('/src/assets/monitoring-white.svg')]" />
              Logs
            </button>
          )}
          {modeConfig[effectiveMode].showAccessDetails && (
            <button
              className="hover:bg-vi</button>olets-are-blue border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={() => setAgentDetails('ACTIVE')}
            >
              Access Details
            </button>
          )}
          <button
            disabled={!isPublishable() || !hasChanges}
            className={`${!isPublishable() || !hasChanges ? 'cursor-not-allowed opacity-30' : ''} bg-purple-30 hover:bg-violets-are-blue flex w-28 items-center justify-center rounded-3xl py-2 text-sm font-medium text-white`}
            onClick={handlePublish}
          >
            <span className="flex items-center justify-center transition-all duration-200">
              {publishLoading ? (
                <Spinner size="small" color="white" />
              ) : (
                modeConfig[effectiveMode].buttonText
              )}
            </span>
          </button>
        </div>
      </div>
      <div className="mt-5 flex w-full grid-cols-5 flex-col gap-10 min-[1180px]:grid min-[1180px]:gap-5">
        <div className="col-span-2 flex flex-col gap-5">
          <div className="rounded-[30px] bg-[#F6F6F6] px-6 py-3 dark:bg-[#383838] dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">Meta</h2>
            <input
              className="border-silver text-jet dark:bg-raisin-black dark:text-bright-gray dark:placeholder:text-silver mt-3 w-full rounded-3xl border bg-white px-5 py-3 text-sm outline-hidden placeholder:text-gray-400 dark:border-[#7E7E7E]"
              type="text"
              value={agent.name}
              placeholder="Agent name"
              onChange={(e) => setAgent({ ...agent, name: e.target.value })}
            />
            <textarea
              className="border-silver text-jet dark:bg-raisin-black dark:text-bright-gray dark:placeholder:text-silver mt-3 h-32 w-full rounded-3xl border bg-white px-5 py-4 text-sm outline-hidden placeholder:text-gray-400 dark:border-[#7E7E7E]"
              placeholder="Describe your agent"
              value={agent.description}
              onChange={(e) =>
                setAgent({ ...agent, description: e.target.value })
              }
            />
            <div className="mt-3">
              <FileUpload
                showPreview
                className="dark:bg-raisin-black"
                onUpload={handleUpload}
                onRemove={() => setImageFile(null)}
                uploadText={[
                  { text: 'Click to upload', colorClass: 'text-[#7D54D1]' },
                  {
                    text: ' or drag and drop',
                    colorClass: 'text-[#525252]',
                  },
                ]}
              />
            </div>
          </div>
          <div className="rounded-[30px] bg-[#F6F6F6] px-6 py-3 dark:bg-[#383838] dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">Source</h2>
            <div className="mt-3">
              <div className="flex flex-wrap items-center gap-1">
                <button
                  ref={sourceAnchorButtonRef}
                  onClick={() => setIsSourcePopupOpen(!isSourcePopupOpen)}
                  className={`border-silver dark:bg-raisin-black w-full truncate rounded-3xl border bg-white px-5 py-3 text-left text-sm dark:border-[#7E7E7E] ${
                    selectedSourceIds.size > 0
                      ? 'text-jet dark:text-bright-gray'
                      : 'dark:text-silver text-gray-400'
                  }`}
                >
                  {selectedSourceIds.size > 0
                    ? Array.from(selectedSourceIds)
                        .map(
                          (id) =>
                            sourceDocs?.find(
                              (source) =>
                                source.id === id ||
                                source.name === id ||
                                source.retriever === id,
                            )?.name,
                        )
                        .filter(Boolean)
                        .join(', ')
                    : 'Select source'}
                </button>
                <MultiSelectPopup
                  isOpen={isSourcePopupOpen}
                  onClose={() => setIsSourcePopupOpen(false)}
                  anchorRef={sourceAnchorButtonRef}
                  options={
                    sourceDocs?.map((doc: Doc) => ({
                      id: doc.id || doc.retriever || doc.name,
                      label: doc.name,
                      icon: <img src={SourceIcon} alt="" />,
                    })) || []
                  }
                  selectedIds={selectedSourceIds}
                  onSelectionChange={(newSelectedIds: Set<string | number>) => {
                    setSelectedSourceIds(newSelectedIds);
                    setIsSourcePopupOpen(false);
                  }}
                  title="Select Source"
                  searchPlaceholder="Search sources..."
                  noOptionsMessage="No source available"
                  singleSelect={true}
                />
              </div>
              <div className="mt-3">
                <Dropdown
                  options={chunks}
                  selectedValue={agent.chunks ? agent.chunks : null}
                  onSelect={(value: string) =>
                    setAgent({ ...agent, chunks: value })
                  }
                  size="w-full"
                  rounded="3xl"
                  border="border"
                  buttonClassName="bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]"
                  optionsClassName="bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]"
                  placeholder="Chunks per query"
                  placeholderClassName="text-gray-400 dark:text-silver"
                  contentSize="text-sm"
                />
              </div>
            </div>
          </div>
          <div className="rounded-[30px] bg-[#F6F6F6] px-6 py-3 dark:bg-[#383838] dark:text-[#E0E0E0]">
            <div className="flex flex-wrap items-end gap-1">
              <div className="min-w-20 grow basis-full sm:basis-0">
                <Prompts
                  prompts={prompts}
                  selectedPrompt={
                    prompts.find((prompt) => prompt.id === agent.prompt_id) ||
                    prompts[0]
                  }
                  onSelectPrompt={(name, id, type) =>
                    setAgent({ ...agent, prompt_id: id })
                  }
                  setPrompts={setPrompts}
                  title="Prompt"
                  titleClassName="text-lg font-semibold dark:text-[#E0E0E0]"
                  showAddButton={false}
                  dropdownProps={{
                    size: 'w-full',
                    rounded: '3xl',
                    border: 'border',
                    buttonClassName:
                      'bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]',
                    optionsClassName:
                      'bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]',
                    placeholderClassName: 'text-gray-400 dark:text-silver',
                    contentSize: 'text-sm',
                  }}
                />
              </div>
              <button
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue w-20 shrink-0 basis-full rounded-3xl border-2 border-solid px-5 py-[11px] text-sm transition-colors hover:text-white sm:basis-auto"
                onClick={() => setAddPromptModal('ACTIVE')}
              >
                Add
              </button>
            </div>
          </div>
          <div className="rounded-[30px] bg-[#F6F6F6] px-6 py-3 dark:bg-[#383838] dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">Tools</h2>
            <div className="mt-3 flex flex-wrap items-center gap-1">
              <button
                ref={toolAnchorButtonRef}
                onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
                className={`border-silver dark:bg-raisin-black w-full truncate rounded-3xl border bg-white px-5 py-3 text-left text-sm dark:border-[#7E7E7E] ${
                  selectedToolIds.size > 0
                    ? 'text-jet dark:text-bright-gray'
                    : 'dark:text-silver text-gray-400'
                }`}
              >
                {selectedToolIds.size > 0
                  ? Array.from(selectedToolIds)
                      .map(
                        (id) => userTools.find((tool) => tool.id === id)?.label,
                      )
                      .filter(Boolean)
                      .join(', ')
                  : 'Select tools'}
              </button>
              <MultiSelectPopup
                isOpen={isToolsPopupOpen}
                onClose={() => setIsToolsPopupOpen(false)}
                anchorRef={toolAnchorButtonRef}
                options={userTools}
                selectedIds={selectedToolIds}
                onSelectionChange={(newSelectedIds: Set<string | number>) =>
                  setSelectedToolIds(newSelectedIds)
                }
                title="Select Tools"
                searchPlaceholder="Search tools..."
                noOptionsMessage="No tools available"
              />
            </div>
          </div>
          <div className="rounded-[30px] bg-[#F6F6F6] px-6 py-3 dark:bg-[#383838] dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">Agent type</h2>
            <div className="mt-3">
              <Dropdown
                options={agentTypes}
                selectedValue={
                  agent.agent_type
                    ? agentTypes.find((type) => type.value === agent.agent_type)
                        ?.label || null
                    : null
                }
                onSelect={(option: { label: string; value: string }) =>
                  setAgent({ ...agent, agent_type: option.value })
                }
                size="w-full"
                rounded="3xl"
                border="border"
                buttonClassName="bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]"
                optionsClassName="bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]"
                placeholder="Select type"
                placeholderClassName="text-gray-400 dark:text-silver"
                contentSize="text-sm"
              />
            </div>
          </div>
        </div>
        <div className="col-span-3 flex flex-col gap-3 rounded-[30px] bg-[#F6F6F6] px-6 py-3 dark:bg-[#383838] dark:text-[#E0E0E0]">
          <h2 className="text-lg font-semibold">Preview</h2>
          <AgentPreviewArea />
        </div>
      </div>
      <ConfirmationModal
        message="Are you sure you want to delete this agent?"
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel="Delete"
        handleSubmit={() => {
          handleDelete(agent.id || '');
          setDeleteConfirmation('INACTIVE');
        }}
        cancelLabel="Cancel"
        variant="danger"
      />
      <AgentDetailsModal
        agent={agent}
        mode={effectiveMode}
        modalState={agentDetails}
        setModalState={setAgentDetails}
      />
      <AddPromptModal
        prompts={prompts}
        setPrompts={setPrompts}
        isOpen={addPromptModal}
        onClose={() => setAddPromptModal('INACTIVE')}
        onSelect={(name: string, id: string, type: string) => {
          setAgent({ ...agent, prompt_id: id });
        }}
      />
    </div>
  );
}

function AgentPreviewArea() {
  const selectedAgent = useSelector(selectSelectedAgent);
  return (
    <div className="dark:bg-raisin-black h-full w-full rounded-[30px] border border-[#F6F6F6] bg-white max-[1180px]:h-192 dark:border-[#7E7E7E]">
      {selectedAgent?.status === 'published' ? (
        <div className="flex h-full w-full flex-col justify-end overflow-auto rounded-[30px]">
          <AgentPreview />
        </div>
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2">
          <span className="block h-12 w-12 bg-[url('/src/assets/science-spark.svg')] bg-contain bg-center bg-no-repeat transition-all dark:bg-[url('/src/assets/science-spark-dark.svg')]" />{' '}
          <p className="dark:text-gray-4000 text-xs text-[#18181B]">
            Published agents can be previewed here
          </p>
        </div>
      )}
    </div>
  );
}

function AddPromptModal({
  prompts,
  setPrompts,
  isOpen,
  onClose,
  onSelect,
}: {
  prompts: Prompt[];
  setPrompts?: React.Dispatch<React.SetStateAction<Prompt[]>>;
  isOpen: ActiveState;
  onClose: () => void;
  onSelect?: (name: string, id: string, type: string) => void;
}) {
  const token = useSelector(selectToken);

  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptContent, setNewPromptContent] = useState('');

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
      onClose();
      setNewPromptName('');
      setNewPromptContent('');
      onSelect?.(newPromptName, newPrompt.id, newPromptContent);
    } catch (error) {
      console.error('Error adding prompt:', error);
    }
  };
  return (
    <PromptsModal
      modalState={isOpen}
      setModalState={onClose}
      type="ADD"
      existingPrompts={prompts}
      newPromptName={newPromptName}
      setNewPromptName={setNewPromptName}
      newPromptContent={newPromptContent}
      setNewPromptContent={setNewPromptContent}
      editPromptName={''}
      setEditPromptName={() => undefined}
      editPromptContent={''}
      setEditPromptContent={() => undefined}
      currentPromptEdit={{ id: '', name: '', type: '' }}
      handleAddPrompt={handleAddPrompt}
    />
  );
}
