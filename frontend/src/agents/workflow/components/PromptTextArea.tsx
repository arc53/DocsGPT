import { Braces, Plus, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Edge, Node } from 'reactflow';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Popover,
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
          <span key={i} className="text-gray-900 dark:text-white">
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
  const [search, setSearch] = useState('');

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
    <div className="flex w-full flex-col overflow-hidden">
      <div className="border-border flex items-center gap-2 border-b px-3 py-2">
        <Search className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
        <Input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search variables..."
          className="h-auto rounded-none border-0 px-0 py-0 text-sm text-gray-800 shadow-none focus-visible:ring-0 md:text-sm dark:border-0 dark:text-gray-200"
        />
      </div>

      <div className="max-h-48 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="text-muted-foreground px-3 py-4 text-center text-xs">
            No variables found
          </div>
        ) : (
          Array.from(grouped.entries()).map(([section, vars]) => (
            <div key={section}>
              <div className="text-muted-foreground truncate px-3 pt-2.5 pb-1 text-xs font-semibold tracking-wider uppercase">
                {section}
              </div>
              {vars.map((v) => (
                <Button
                  key={`${section}-${v.templatePath}`}
                  type="button"
                  variant="ghost"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onSelect(v.templatePath);
                  }}
                  className="h-auto w-full justify-start gap-2 rounded-none px-3 py-1.5 text-left text-sm font-normal"
                >
                  <Braces className="text-primary h-3.5 w-3.5 shrink-0" />
                  <span className="truncate font-medium text-gray-800 dark:text-gray-200">
                    {v.label}
                  </span>
                </Button>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [showDropdown, setShowDropdown] = useState(false);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 });
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

      const wrapper = wrapperRef.current;
      if (!wrapper) return;

      setDropdownPos({
        top: wrapper.offsetHeight + 4,
        left: 0,
      });
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

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as HTMLElement)
      ) {
        setShowDropdown(false);
      }
    };
    if (showDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
      return () =>
        document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showDropdown]);

  return (
    <div>
      {label && (
        <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
          {label}
        </label>
      )}
      <div
        ref={wrapperRef}
        className="border-border focus-within:ring-ring bg-card relative rounded-xl border transition-all focus-within:ring-2"
      >
        <div
          ref={overlayRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-hidden rounded-xl border border-transparent px-3 py-2 text-sm wrap-break-word whitespace-pre-wrap"
        >
          {value ? (
            <HighlightedOverlay text={value} />
          ) : (
            <span className="text-gray-400 dark:text-gray-500">
              {placeholder}
            </span>
          )}
        </div>

        <textarea
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
          className="focus-visible:ring-ring/50 focus-visible:border-ring relative w-full rounded-xl bg-transparent px-3 pt-2 pb-8 text-sm caret-black outline-none focus-visible:ring-[3px] dark:caret-white"
          style={{
            color: 'transparent',
            WebkitTextFillColor: 'transparent',
          }}
          rows={rows}
          placeholder={placeholder}
          spellCheck={false}
        />

        <div className="absolute right-4 bottom-1.5 z-10">
          <Popover open={contextOpen} onOpenChange={setContextOpen}>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="text-primary hover:bg-primary/10 h-auto gap-1 px-2 py-1 text-xs font-medium"
              >
                <Plus className="h-3 w-3" />
                Add context
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              side="top"
              className="border-border bg-card w-60 rounded-xl border p-0 shadow-lg"
              onOpenAutoFocus={(e) => e.preventDefault()}
            >
              <VariableListWithSearch
                variables={variables}
                onSelect={insertVariableFromButton}
              />
            </PopoverContent>
          </Popover>
        </div>

        {showDropdown && filtered.length > 0 && (
          <div
            ref={dropdownRef}
            className="border-border bg-card absolute z-50 w-64 rounded-xl border shadow-lg"
            style={{ top: dropdownPos.top, left: dropdownPos.left }}
          >
            <VariableListWithSearch
              variables={filtered}
              onSelect={insertVariable}
            />
          </div>
        )}
      </div>
    </div>
  );
}
