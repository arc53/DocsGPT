import { Braces, Plus, Search } from 'lucide-react';
import { useCallback, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Edge, Node } from 'reactflow';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField, FormFieldBoundary } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

export interface WorkflowVariable {
  label: string;
  templatePath: string;
  section: string;
  // True when the variable resolves to artifact reference(s) at run time
  // (uploaded input_documents, code-node outputs) rather than plain LLM/state
  // TEXT. Only artifact-bearing variables may be picked as node Documents;
  // selecting a text output there makes the engine append the literal variable
  // name and the node hard-fails. Heuristic keyed on the producing node type.
  producesArtifact?: boolean;
}

const GLOBAL_CONTEXT_VARIABLES: WorkflowVariable[] = [
  {
    label: 'source.content',
    templatePath: 'source.content',
    section: 'Global context',
  },
  {
    label: 'source.summaries',
    templatePath: 'source.summaries',
    section: 'Global context',
  },
  {
    label: 'source.documents',
    templatePath: 'source.documents',
    section: 'Global context',
  },
  {
    label: 'source.count',
    templatePath: 'source.count',
    section: 'Global context',
  },
  {
    label: 'system.date',
    templatePath: 'system.date',
    section: 'Global context',
  },
  {
    label: 'system.time',
    templatePath: 'system.time',
    section: 'Global context',
  },
  {
    label: 'system.timestamp',
    templatePath: 'system.timestamp',
    section: 'Global context',
  },
  {
    label: 'system.request_id',
    templatePath: 'system.request_id',
    section: 'Global context',
  },
  {
    label: 'system.user_id',
    templatePath: 'system.user_id',
    section: 'Global context',
  },
  {
    label: 'artifacts.artifact(id)',
    templatePath: 'artifacts.artifact(id)',
    section: 'Global context',
  },
];

function toAgentTemplatePath(variableName: string): string {
  const trimmed = variableName.trim();
  if (!trimmed) return 'agent';

  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(trimmed)) {
    return `agent.${trimmed}`;
  }

  const escaped = trimmed.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  return `agent['${escaped}']`;
}

function getUpstreamNodeIds(nodeId: string, edges: Edge[]): Set<string> {
  const upstream = new Set<string>();
  const queue = [nodeId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const edge of edges) {
      if (edge.target === current && !upstream.has(edge.source)) {
        upstream.add(edge.source);
        queue.push(edge.source);
      }
    }
  }

  return upstream;
}

export function extractUpstreamVariables(
  nodes: Node[],
  edges: Edge[],
  selectedNodeId: string,
): WorkflowVariable[] {
  const variables: WorkflowVariable[] = [
    {
      label: 'agent.query',
      templatePath: 'agent.query',
      section: 'Workflow input',
    },
    {
      label: 'agent.chat_history',
      templatePath: 'agent.chat_history',
      section: 'Workflow input',
    },
    {
      label: 'agent.input_documents',
      templatePath: 'agent.input_documents',
      section: 'Workflow input',
      // Uploaded documents are artifact references.
      producesArtifact: true,
    },
    ...GLOBAL_CONTEXT_VARIABLES,
  ];
  const seen = new Set(variables.map((variable) => variable.templatePath));
  const upstreamIds = getUpstreamNodeIds(selectedNodeId, edges);

  const pushNodeOutput = (
    node: Node,
    outputName: string,
    sectionFallback: string,
    producesArtifact: boolean,
  ) => {
    const templatePath = toAgentTemplatePath(outputName);
    if (seen.has(templatePath)) return;
    seen.add(templatePath);
    variables.push({
      label: templatePath,
      templatePath,
      section: node.data.title || node.data.label || sectionFallback,
      producesArtifact,
    });
  };

  for (const node of nodes) {
    if (!upstreamIds.has(node.id)) continue;

    if (node.type === 'agent' || node.type === 'code') {
      // Agent and code nodes both expose `node_<id>_output` and an optional
      // `output_variable`, but only code-node outputs resolve to artifact
      // references in the engine — agent outputs are LLM TEXT. So both feed the
      // prompt-variable popover, while only code outputs are offered as
      // Documents (see toDocumentVariableOptions / producesArtifact).
      const producesArtifact = node.type === 'code';
      const sectionFallback = node.type === 'code' ? 'Code' : 'Agent';
      pushNodeOutput(
        node,
        `node_${node.id}_output`,
        sectionFallback,
        producesArtifact,
      );

      const outputVariable = String(
        node.data?.config?.output_variable || '',
      ).trim();
      if (outputVariable) {
        pushNodeOutput(node, outputVariable, sectionFallback, producesArtifact);
      }
    }

    if (node.type === 'state') {
      const operations = node.data?.config?.operations;
      if (!Array.isArray(operations)) continue;

      for (const operation of operations) {
        const targetVariable = String(operation?.target_variable || '').trim();
        if (!targetVariable) continue;

        const templatePath = toAgentTemplatePath(targetVariable);
        if (seen.has(templatePath)) continue;

        seen.add(templatePath);
        variables.push({
          label: templatePath,
          templatePath,
          section: node.data.title || node.data.label || 'Set State',
        });
      }
    }
  }

  return variables;
}

// Built-in section names (and the unnamed-node fallbacks) shown translated;
// a node's own title is a value and shows as written.
const SECTION_LABEL_KEYS: Record<string, string> = {
  'Global context': 'agents.workflow.variables.globalContext',
  'Workflow input': 'agents.workflow.variables.workflowInput',
  Agent: 'agents.workflow.nodes.agent',
  Code: 'agents.workflow.nodes.code',
  'Set State': 'agents.workflow.nodes.setState',
};

function groupBySection(
  vars: WorkflowVariable[],
): Map<string, WorkflowVariable[]> {
  const groups = new Map<string, WorkflowVariable[]>();
  for (const v of vars) {
    const list = groups.get(v.section) ?? [];
    list.push(v);
    groups.set(v.section, list);
  }
  return groups;
}

function HighlightedOverlay({ text }: { text: string }) {
  const parts = text.split(/(\{\{[^}]*\}\})/g);
  return (
    <>
      {parts.map((part, i) =>
        /^\{\{[^}]*\}\}$/.test(part) ? (
          <span key={i} className="text-primary font-medium">
            {part}
          </span>
        ) : (
          <span key={i} className="text-foreground">
            {part}
          </span>
        ),
      )}
    </>
  );
}

function VariableListWithSearch({
  variables,
  onSelect,
}: {
  variables: WorkflowVariable[];
  onSelect: (templatePath: string) => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  // Own id, and a FormFieldBoundary below: the "Add context" popover renders
  // inside PromptTextArea's FormField (through a portal), whose context would
  // otherwise hand this search box the textarea's id and floating placeholder.
  const searchId = useId();

  const filtered = useMemo(
    () =>
      variables.filter((v) =>
        `${v.label} ${v.templatePath}`
          .toLowerCase()
          .includes(search.toLowerCase()),
      ),
    [variables, search],
  );

  const grouped = useMemo(() => groupBySection(filtered), [filtered]);

  return (
    <FormFieldBoundary>
      <div className="flex w-full flex-col overflow-hidden">
        <div className="border-border flex items-center gap-2 border-b px-3 py-2">
          <Search className="text-muted-foreground size-3.5 shrink-0" />
          <Input
            id={searchId}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('agents.workflow.variables.searchPlaceholder')}
            variant="bare"
          />
        </div>

        <div className="max-h-48 overflow-y-auto">
          {filtered.length === 0 ? (
            <EmptyState
              size="xs"
              illustration="none"
              title={t('agents.workflow.variables.empty')}
            />
          ) : (
            Array.from(grouped.entries()).map(([section, vars]) => (
              <div key={section}>
                <div className="text-muted-foreground truncate px-3 pt-2.5 pb-1 text-xs font-semibold tracking-wider uppercase">
                  {SECTION_LABEL_KEYS[section]
                    ? t(SECTION_LABEL_KEYS[section])
                    : section}
                </div>
                {vars.map((v) => (
                  <Button
                    key={`${section}-${v.templatePath}`}
                    type="button"
                    variant="ghost"
                    size="sm"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onSelect(v.templatePath);
                    }}
                    className="w-full justify-start"
                  >
                    <Braces className="text-primary size-3.5 shrink-0" />
                    <span className="text-foreground truncate font-medium">
                      {v.label}
                    </span>
                  </Button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>
    </FormFieldBoundary>
  );
}

interface PromptTextAreaProps {
  value: string;
  onChange: (value: string) => void;
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string;
  placeholder?: string;
  rows?: number;
  label?: string;
}

export default function PromptTextArea({
  value,
  onChange,
  nodes,
  edges,
  selectedNodeId,
  placeholder,
  rows = 4,
  label,
}: PromptTextAreaProps) {
  const { t } = useTranslation();
  const textareaId = useId();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [showDropdown, setShowDropdown] = useState(false);
  const [filterText, setFilterText] = useState('');
  const [cursorInsertPos, setCursorInsertPos] = useState<number | null>(null);
  const [contextOpen, setContextOpen] = useState(false);

  const variables = useMemo(
    () => extractUpstreamVariables(nodes, edges, selectedNodeId),
    [nodes, edges, selectedNodeId],
  );
  const filtered = useMemo(
    () =>
      variables.filter((v) =>
        `${v.label} ${v.templatePath}`
          .toLowerCase()
          .includes(filterText.toLowerCase()),
      ),
    [variables, filterText],
  );

  const checkForTrigger = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const cursorPos = textarea.selectionStart;
    const textBeforeCursor = value.slice(0, cursorPos);
    const triggerMatch = textBeforeCursor.match(
      /\{\{\s*([A-Za-z0-9_.[\]'"]*)$/,
    );

    if (triggerMatch) {
      setFilterText(triggerMatch[1].trim());
      setCursorInsertPos(cursorPos);
      setShowDropdown(true);
    } else {
      setShowDropdown(false);
    }
  }, [value]);

  const insertVariable = useCallback(
    (templatePath: string) => {
      if (cursorInsertPos === null) return;

      const textBeforeCursor = value.slice(0, cursorInsertPos);
      const triggerMatch = textBeforeCursor.match(
        /\{\{\s*([A-Za-z0-9_.[\]'"]*)$/,
      );
      if (!triggerMatch) return;

      const startPos = cursorInsertPos - triggerMatch[0].length;
      const insertion = `{{ ${templatePath} }}`;
      const newValue =
        value.slice(0, startPos) + insertion + value.slice(cursorInsertPos);

      onChange(newValue);
      setShowDropdown(false);

      requestAnimationFrame(() => {
        const newCursorPos = startPos + insertion.length;
        textareaRef.current?.setSelectionRange(newCursorPos, newCursorPos);
        textareaRef.current?.focus();
      });
    },
    [value, cursorInsertPos, onChange],
  );

  const insertVariableFromButton = useCallback(
    (templatePath: string) => {
      const textarea = textareaRef.current;
      const cursorPos = textarea?.selectionStart ?? value.length;
      const insertion = `{{ ${templatePath} }}`;
      const newValue =
        value.slice(0, cursorPos) + insertion + value.slice(cursorPos);

      onChange(newValue);
      setContextOpen(false);

      requestAnimationFrame(() => {
        const newCursorPos = cursorPos + insertion.length;
        textareaRef.current?.setSelectionRange(newCursorPos, newCursorPos);
        textareaRef.current?.focus();
      });
    },
    [value, onChange],
  );

  // The mention menu opens under the field and leaves focus in the textarea,
  // so typing keeps filtering it.
  const field = (
    <PopoverAnchor asChild>
      <div className="border-border focus-within:ring-ring bg-card relative rounded-xl border transition-shadow focus-within:ring-2">
        <div
          ref={overlayRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-hidden rounded-xl border border-transparent px-3 py-2 text-sm wrap-break-word whitespace-pre-wrap"
        >
          {value ? (
            <HighlightedOverlay text={value} />
          ) : (
            // Under a floating label the example waits for focus, like
            // ui/Textarea, so it doesn't collide with the resting label.
            <span
              className={
                label
                  ? 'text-muted-foreground invisible group-focus-within/float:visible'
                  : 'text-muted-foreground'
              }
            >
              {placeholder}
            </span>
          )}
        </div>

        <textarea
          id={textareaId}
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setTimeout(checkForTrigger, 0);
          }}
          onKeyUp={checkForTrigger}
          onKeyDown={(e) => {
            if (showDropdown && e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              setShowDropdown(false);
            }
          }}
          onScroll={() => {
            if (overlayRef.current && textareaRef.current) {
              overlayRef.current.scrollTop = textareaRef.current.scrollTop;
            }
          }}
          className="focus-visible:ring-ring/50 focus-visible:border-ring caret-foreground relative w-full rounded-xl bg-transparent px-3 pt-2 pb-8 text-sm text-transparent outline-none focus-visible:ring-3"
          rows={rows}
          placeholder={placeholder}
          spellCheck={false}
        />

        <div className="absolute right-4 bottom-1.5 z-10">
          <Popover open={contextOpen} onOpenChange={setContextOpen}>
            <PopoverTrigger asChild>
              <Button type="button" variant="link" size="xs">
                <Plus className="size-3" />
                {t('agents.workflow.variables.addContext')}
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              side="top"
              className="w-60 p-0"
              onOpenAutoFocus={(e) => e.preventDefault()}
            >
              <VariableListWithSearch
                variables={variables}
                onSelect={insertVariableFromButton}
              />
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </PopoverAnchor>
  );

  return (
    <Popover
      open={showDropdown && filtered.length > 0}
      onOpenChange={(open) => {
        if (!open) setShowDropdown(false);
      }}
    >
      {label ? (
        <FormField label={label} id={textareaId}>
          {field}
        </FormField>
      ) : (
        field
      )}
      <PopoverContent
        align="start"
        className="w-64 p-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onInteractOutside={(e) => {
          if (textareaRef.current?.contains(e.target as HTMLElement)) {
            e.preventDefault();
          }
        }}
      >
        <VariableListWithSearch
          variables={filtered}
          onSelect={insertVariable}
        />
      </PopoverContent>
    </Popover>
  );
}
