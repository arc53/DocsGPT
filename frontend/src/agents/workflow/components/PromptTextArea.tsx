import { Braces, Plus, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Edge, Node } from 'reactflow';

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

interface WorkflowVariable {
  label: string;
  templatePath: string;
  section: string;
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

function extractUpstreamVariables(
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
    ...GLOBAL_CONTEXT_VARIABLES,
  ];
  const seen = new Set(variables.map((variable) => variable.templatePath));
  const upstreamIds = getUpstreamNodeIds(selectedNodeId, edges);

  for (const node of nodes) {
    if (!upstreamIds.has(node.id)) continue;

    if (node.type === 'agent') {
      const defaultOutputTemplatePath = toAgentTemplatePath(
        `node_${node.id}_output`,
      );
      if (!seen.has(defaultOutputTemplatePath)) {
        seen.add(defaultOutputTemplatePath);
        variables.push({
          label: defaultOutputTemplatePath,
          templatePath: defaultOutputTemplatePath,
          section: node.data.title || node.data.label || 'Agent',
        });
      }

      const outputVariable = String(
        node.data?.config?.output_variable || '',
      ).trim();
      if (outputVariable) {
        const templatePath = toAgentTemplatePath(outputVariable);
        if (!seen.has(templatePath)) {
          seen.add(templatePath);
          variables.push({
            label: templatePath,
            templatePath,
            section: node.data.title || node.data.label || 'Agent',
          });
        }
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
          <span key={i} className="text-violets-are-blue font-medium">
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
      <div className="flex items-center gap-2 border-b border-[#E5E5E5] px-3 py-2 dark:border-[#3A3A3A]">
        <Search className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search variables..."
          className="placeholder:text-muted-foreground w-full bg-transparent text-sm text-gray-800 outline-none dark:text-gray-200"
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
              <div className="text-muted-foreground truncate px-3 pt-2.5 pb-1 text-[10px] font-semibold tracking-wider uppercase">
                {section}
              </div>
              {vars.map((v) => (
                <button
                  key={`${section}-${v.templatePath}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onSelect(v.templatePath);
                  }}
                  className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-gray-50 dark:hover:bg-[#383838]"
                >
                  <Braces className="text-violets-are-blue h-3.5 w-3.5 shrink-0" />
                  <span className="truncate font-medium text-gray-800 dark:text-gray-200">
                    {v.label}
                  </span>
                </button>
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
        className="border-light-silver focus-within:ring-purple-30 relative rounded-xl border bg-white transition-all focus-within:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C]"
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
          className="relative w-full rounded-xl bg-transparent px-3 pt-2 pb-8 text-sm caret-black outline-none dark:caret-white"
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
              <button
                type="button"
                className="text-violets-are-blue hover:bg-violets-are-blue/10 flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors"
              >
                <Plus className="h-3 w-3" />
                Add context
              </button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              side="top"
              className="w-60 rounded-xl border border-[#E5E5E5] bg-white p-0 shadow-lg dark:border-[#3A3A3A] dark:bg-[#2C2C2C]"
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
            className="absolute z-50 w-64 rounded-xl border border-[#E5E5E5] bg-white shadow-lg dark:border-[#3A3A3A] dark:bg-[#2C2C2C]"
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
