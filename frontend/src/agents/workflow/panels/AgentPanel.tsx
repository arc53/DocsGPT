import {
  type MouseEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { type NavigateOptions } from 'react-router-dom';
import { type Edge, type Node } from 'reactflow';

import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { MultiSelectTrigger } from '@/components/ui/multi-select';
import { SectionHeader } from '@/components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SettingRow, SettingRows } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import {
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
} from '../../../connectors/connectorsSlice';
import {
  selectSourceDocs,
  selectToken,
} from '../../../preferences/preferenceSlice';
import type { AppDispatch } from '../../../store';
import type { Connection } from '../../../connectors/types';
import KnowledgePicker from '../../components/KnowledgePicker';
import ToolsPicker from '../../components/ToolsPicker';
import { useAttachAddedTools } from '../../hooks/useAttachAddedTools';
import {
  getToolDisplayName,
  isWorkflowNodeToolVisible,
} from '../../../utils/toolUtils';
import type { RetryConfig } from '../../types/workflow';
import NodeDocumentsControl from '../components/NodeDocumentsControl';
import NodeRetryControl from '../components/NodeRetryControl';
import PromptTextArea from '../components/PromptTextArea';
import {
  DEFAULT_FILE_PASSING,
  FILE_PASSING_OPTIONS,
  FilePassing,
  normalizeFilePassing,
} from '../documentConfig';
import { effectiveRetry } from '../retryConfig';
import { NO_ESCAPE, schemaErrorText, type UserTool } from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

import type { Model } from '../../../models/types';

interface AgentPanelProps extends NodePanelBodyProps {
  nodes: Node[];
  edges: Edge[];
  availableModels: Model[];
  availableTools: UserTool[];
  /**
   * Names of the tools and sources the workflow's nodes reference, whoever
   * owns them: a selected one missing from the caller's own options (the
   * owner's private tool) still gets an option, so it can be removed.
   */
  attachedTools?: { id: string; label: string; name?: string }[];
  attachedSources?: { id: string; label: string }[];
  /** Upstream file variables the agent can read. */
  documentOptions: { value: string; label: string }[];
  /** The structured-output schema as typed. */
  jsonSchemaText: string;
  /** The schema's validation fragment, or null. */
  jsonSchemaError: string | null;
  /** False when the picked model can't return structured output. */
  modelSupportsStructuredOutput: boolean;
  onJsonSchemaChange: (text: string) => void;
  /** The workflow's retry defaults, which an unset retry field inherits. */
  retryDefaults?: RetryConfig | null;
  /**
   * Reloads the builder's tool list and returns it, so a tool added from the
   * Tools picker's footer can go on the node.
   */
  onReloadTools: () => Promise<UserTool[]>;
  /**
   * A picker footer's Go to link, after the picker closes: the builder
   * prevents it and asks first while the workflow has unsaved changes.
   */
  onNavigateAway?: (event: MouseEvent<HTMLAnchorElement>) => void;
  /**
   * Leaves for a page from a dialog opened here (Add tool's Browse all, the
   * API tool editor, Try it in chat): the builder asks first while the
   * workflow has unsaved changes.
   */
  onLeaveTo?: (to: string, options?: NavigateOptions) => void;
  /** Signs a broken connection behind the caller's tools in again. */
  onReconnect?: (connection: Connection, mcpToolId?: string) => void;
}

/** A picked id added when missing, removed when present. */
const toggled = (ids: string[], id: string): string[] =>
  ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];

const SCHEMA_PLACEHOLDER = `{
  "type": "object",
  "properties": {
    "summary": { "type": "string" }
  },
  "required": ["summary"]
}`;

/**
 * Whether any advanced setting (documents, file passing, structured output,
 * retries) differs from its default, so the disclosure opens on its own.
 *
 * Args:
 *   config: The agent node's config.
 *   jsonSchemaText: The schema as typed.
 *   jsonSchemaError: The schema's validation fragment, or null.
 *
 * Returns:
 *   True when the advanced settings should start open.
 */
export function hasAdvancedAgentSettings(
  config: Record<string, unknown> | undefined,
  jsonSchemaText: string,
  jsonSchemaError: string | null,
): boolean {
  const inputDocuments = config?.input_documents;
  return (
    (Array.isArray(inputDocuments) && inputDocuments.length > 0) ||
    normalizeFilePassing(config?.file_passing) !== DEFAULT_FILE_PASSING ||
    (config?.json_schema !== undefined && config?.json_schema !== null) ||
    jsonSchemaText.trim() !== '' ||
    Boolean(jsonSchemaError) ||
    (config?.retry !== undefined && config?.retry !== null)
  );
}

/**
 * Settings for an AI Agent node, grouped Model, Prompt, Knowledge and Output
 * like classic Overview, with documents, file passing, structured output and
 * retries under an Advanced settings disclosure.
 */
export default function AgentPanel({
  node,
  onUpdate,
  nodes,
  edges,
  availableModels,
  availableTools,
  attachedTools = [],
  attachedSources = [],
  documentOptions,
  jsonSchemaText,
  jsonSchemaError,
  modelSupportsStructuredOutput,
  onJsonSchemaChange,
  retryDefaults = null,
  onReloadTools,
  onNavigateAway,
  onLeaveTo,
  onReconnect,
}: AgentPanelProps) {
  const { t } = useTranslation();
  const streamId = useId();
  const advancedId = useId();
  const config = node.data.config || {};
  const [advancedOpen, setAdvancedOpen] = useState(() =>
    hasAdvancedAgentSettings(config, jsonSchemaText, jsonSchemaError),
  );

  const updateConfig = (patch: Record<string, unknown>) =>
    onUpdate({ config: { ...(node.data.config || {}), ...patch } });

  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const storedDocs = useSelector(selectSourceDocs);
  const connections = useSelector(selectConnections);
  const catalog = useSelector(selectConnectorCatalog);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  // A node saves its sources by id, so a source without one can't be picked.
  const sourceDocs = useMemo(
    () => (storedDocs ?? []).filter((doc) => Boolean(doc.id)),
    [storedDocs],
  );
  const pickedSources: string[] = config.sources || [];
  const pickedTools: string[] = config.tools || [];

  // An upload finishes after its dialog closes, maybe after the node did:
  // its source goes on this node only while the panel still shows it.
  const latest = useRef({ node, onUpdate });
  const mounted = useRef(false);
  useEffect(() => {
    latest.current = { node, onUpdate };
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const attachUploadedSource = (nodeId: string, sourceId?: string) => {
    if (!sourceId || !mounted.current) return;
    const { node: current, onUpdate: update } = latest.current;
    if (current.id !== nodeId) return;
    const currentConfig = current.data.config || {};
    const sources: string[] = currentConfig.sources || [];
    if (sources.includes(sourceId)) return;
    update({ config: { ...currentConfig, sources: [...sources, sourceId] } });
  };
  // A tool made from the Tools footer's Add tool goes on the node it was
  // added from, once the reloaded list holds it, while the panel shows it.
  const attachCreated = useAttachAddedTools(onReloadTools);
  const attachToolsCreated = (nodeId: string, toolIds: string[]) =>
    attachCreated(toolIds, (created) => {
      const { node: current, onUpdate: update } = latest.current;
      if (current.id !== nodeId) return;
      const currentConfig = current.data.config || {};
      const nodeTools: string[] = currentConfig.tools || [];
      const added = created
        .map((tool) => tool.id)
        .filter((id) => !nodeTools.includes(id));
      if (added.length === 0) return;
      update({ config: { ...currentConfig, tools: [...nodeTools, ...added] } });
    });

  // The rows name the caller's connections and the catalog's services.
  const openPicker = (setOpen: (open: boolean) => void) => (next: boolean) => {
    setOpen(next);
    if (next) dispatch(loadConnectors({ token }));
  };

  const builtinModels = availableModels.filter((m) => m.source !== 'user');
  const userModels = availableModels.filter((m) => m.source === 'user');
  const schemaInvalid = jsonSchemaText.trim() !== '' && jsonSchemaError;
  // Marks a row only in the list; its chip keeps the plain name.
  const attachedDescription = t('agents.form.sponsors.addedByOther');
  // The attached tools picked on this node the caller can't list.
  const attachedOnNode = useMemo(
    () =>
      attachedTools
        .filter((tool) => pickedTools.includes(tool.id))
        .map((tool) => ({
          id: tool.id,
          name: tool.name ?? '',
          display_name: tool.label,
        })),
    [attachedTools, pickedTools],
  );

  // The trigger's chips, in the order they were picked.
  const sourceName = (id: string) =>
    sourceDocs.find((doc) => doc.id === id)?.name ||
    attachedSources.find((item) => item.id === id)?.label ||
    id;
  const toolName = (id: string) => {
    const tool = availableTools.find((item) => item.id === id);
    return (
      (tool && getToolDisplayName(tool)) ||
      attachedTools.find((item) => item.id === id)?.label ||
      id
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.form.sections.model')}
        />
        <div className="flex flex-col gap-5">
          <FormField
            label={t('agents.workflow.builder.agentType')}
            labelSurface="background"
          >
            <Select
              value={config.agent_type || 'classic'}
              onValueChange={(value) => updateConfig({ agent_type: value })}
            >
              <SelectTrigger size="field" className="w-full">
                <SelectValue
                  placeholder={t(
                    'agents.workflow.builder.agentTypePlaceholder',
                  )}
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="classic">
                  {t('agents.form.agentTypes.classic')}
                </SelectItem>
                <SelectItem value="research">
                  {t('agents.form.agentTypes.research')}
                </SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            label={t('agents.workflow.builder.model')}
            labelSurface="background"
          >
            <Select
              value={config.model_id || ''}
              onValueChange={(value) =>
                updateConfig({
                  model_id: value,
                  llm_name:
                    availableModels.find((m) => m.id === value)?.provider || '',
                })
              }
            >
              <SelectTrigger size="field" className="w-full">
                <SelectValue
                  placeholder={t('agents.workflow.builder.modelPlaceholder')}
                />
              </SelectTrigger>
              <SelectContent>
                {builtinModels.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>
                      {t('settings.customModels.modelsGroup.builtin')}
                    </SelectLabel>
                    {builtinModels.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.display_name} · {model.provider}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
                {userModels.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>
                      {t('settings.customModels.modelsGroup.user')}
                    </SelectLabel>
                    {userModels.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.display_name} · {model.provider}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
              </SelectContent>
            </Select>
          </FormField>
        </div>
      </section>

      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.form.sections.prompt')}
        />
        <FormField
          label={t('agents.workflow.builder.systemPrompt')}
          labelSurface="background"
        >
          <Textarea
            value={config.system_prompt ?? ''}
            onChange={(e) => updateConfig({ system_prompt: e.target.value })}
            rows={3}
            placeholder={t('agents.workflow.builder.systemPromptPlaceholder')}
          />
        </FormField>
        <PromptTextArea
          label={t('agents.workflow.builder.promptTemplate')}
          labelSurface="background"
          value={config.prompt_template || ''}
          onChange={(val) => updateConfig({ prompt_template: val })}
          nodes={nodes}
          edges={edges}
          selectedNodeId={node.id}
          placeholder={t('agents.workflow.builder.promptTemplatePlaceholder', {
            ...NO_ESCAPE,
            example: '{{ agent.variable }}',
          })}
        />
      </section>

      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.workflow.builder.knowledge')}
        />
        <FormField
          label={t('agents.workflow.builder.sources')}
          labelSurface="background"
        >
          {/* The panel is docked beside the canvas, not a dialog, so the
              popover needs no modal (on a phone it is its own sheet). */}
          <KnowledgePicker
            open={sourcesOpen}
            onOpenChange={openPicker(setSourcesOpen)}
            docs={sourceDocs}
            selectedIds={pickedSources}
            onToggle={(id) =>
              updateConfig({ sources: toggled(pickedSources, id) })
            }
            connections={connections}
            unlistedLabel={(id) =>
              attachedSources.find((item) => item.id === id)?.label || id
            }
            unlistedLine={() => attachedDescription}
            onNavigate={(event) => onNavigateAway?.(event)}
            onUploaded={(sourceId) => attachUploadedSource(node.id, sourceId)}
            onBrowseConnectors={
              onLeaveTo
                ? () => onLeaveTo('/settings/connectors?capability=sync')
                : undefined
            }
            trigger={
              <MultiSelectTrigger
                labels={pickedSources.map(sourceName)}
                placeholder={t('agents.form.placeholders.selectSources')}
              />
            }
          />
        </FormField>
        <FormField
          label={t('agents.form.sections.tools')}
          labelSurface="background"
        >
          <ToolsPicker
            open={toolsOpen}
            onOpenChange={openPicker(setToolsOpen)}
            tools={availableTools}
            filter={isWorkflowNodeToolVisible}
            attached={attachedOnNode}
            attachedLine={attachedDescription}
            selectedIds={pickedTools}
            onToggle={(id) => updateConfig({ tools: toggled(pickedTools, id) })}
            connections={connections}
            catalog={catalog}
            onReconnect={onReconnect}
            onNavigate={(event) => onNavigateAway?.(event)}
            onReloadTools={() => void onReloadTools().catch(() => undefined)}
            onToolsCreated={(toolIds) =>
              void attachToolsCreated(node.id, toolIds)
            }
            onLeaveTo={onLeaveTo}
            trigger={
              <MultiSelectTrigger
                labels={pickedTools.map(toolName)}
                placeholder={t('agents.form.placeholders.selectTools')}
              />
            }
          />
        </FormField>
      </section>

      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.workflow.builder.output')}
        />
        <FormField
          label={t('agents.workflow.builder.outputVariable')}
          labelSurface="background"
        >
          <Input
            type="text"
            value={config.output_variable || ''}
            onChange={(e) => updateConfig({ output_variable: e.target.value })}
            placeholder={t('agents.workflow.builder.outputVariablePlaceholder')}
          />
        </FormField>
        <SettingRows>
          <SettingRow
            label={t('agents.workflow.builder.streamToUser')}
            description={t('agents.workflow.builder.streamToUserDescription')}
            htmlFor={streamId}
          >
            <Switch
              id={streamId}
              checked={config.stream_to_user ?? true}
              onCheckedChange={(checked) =>
                updateConfig({ stream_to_user: checked })
              }
            />
          </SettingRow>
        </SettingRows>
      </section>

      {/* The 20px gap sits inside the body, so it folds away with it. */}
      <div className="flex flex-col">
        <CollapsibleTrigger
          open={advancedOpen}
          onOpenChange={setAdvancedOpen}
          controls={advancedId}
        >
          {t('agents.workflow.builder.advancedSettings')}
        </CollapsibleTrigger>
        <Collapsible open={advancedOpen} id={advancedId}>
          <div className="flex flex-col gap-5 pt-5">
            <NodeDocumentsControl
              key={node.id}
              value={config.input_documents ?? []}
              onChange={(nextInputDocuments) =>
                updateConfig({ input_documents: nextInputDocuments })
              }
              options={documentOptions}
              label={t('agents.workflow.builder.documents')}
              helpText={t('agents.workflow.builder.documentsHint')}
            />
            <FormField
              label={t('agents.workflow.builder.filePassing')}
              hint={t('agents.workflow.builder.filePassingHint')}
              labelSurface="background"
            >
              <Select
                value={normalizeFilePassing(config.file_passing)}
                onValueChange={(value) =>
                  updateConfig({ file_passing: value as FilePassing })
                }
              >
                <SelectTrigger size="field" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FILE_PASSING_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {t(`agents.workflow.filePassing.${option.value}`, {
                        defaultValue: option.label,
                      })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField
              label={t('agents.workflow.builder.structuredOutput')}
              labelSurface="background"
              hint={
                [
                  !modelSupportsStructuredOutput
                    ? t('agents.workflow.builder.modelNoStructuredOutput')
                    : null,
                  jsonSchemaText.trim() !== '' && !jsonSchemaError
                    ? t('agents.workflow.builder.validSchema')
                    : null,
                ]
                  .filter(Boolean)
                  .join(' ') || undefined
              }
              error={
                schemaInvalid
                  ? t('agents.workflow.builder.invalidSchema', {
                      ...NO_ESCAPE,
                      error: schemaErrorText(t, jsonSchemaError),
                    })
                  : undefined
              }
            >
              <Textarea
                value={jsonSchemaText}
                onChange={(e) => onJsonSchemaChange(e.target.value)}
                className="font-mono"
                rows={4}
                placeholder={SCHEMA_PLACEHOLDER}
              />
            </FormField>
            <NodeRetryControl
              key={node.id}
              value={config.retry}
              onChange={(retry) => updateConfig({ retry })}
              inherited={effectiveRetry(undefined, retryDefaults)}
              showOn
            />
          </div>
        </Collapsible>
      </div>
    </div>
  );
}
