import type { WorkflowVariable } from './components/PromptTextArea';

/** Token meaning "all uploaded input documents" in the input_documents list. */
export const ALL_INPUT_DOCUMENTS_TOKEN = '*';

/** How an agent node receives selected documents. */
export type FilePassing = 'auto' | 'native' | 'extract';

export const DEFAULT_FILE_PASSING: FilePassing = 'auto';

export const FILE_PASSING_OPTIONS: { value: FilePassing; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'native', label: 'Native' },
  { value: 'extract', label: 'Extract' },
];

/** Three-way Documents selector position derived from input_documents. */
export type DocumentsMode = 'all' | 'none' | 'choose';

/** Normalize an unknown file_passing value to a supported option. */
export function normalizeFilePassing(value: unknown): FilePassing {
  return value === 'native' || value === 'extract' || value === 'auto'
    ? value
    : DEFAULT_FILE_PASSING;
}

/** Derive the toggle position from the stored input_documents list. */
export function getDocumentsMode(
  inputDocuments: string[] | undefined,
): DocumentsMode {
  const docs = inputDocuments ?? [];
  if (docs.length === 0) return 'none';
  if (docs.length === 1 && docs[0] === ALL_INPUT_DOCUMENTS_TOKEN) return 'all';
  return 'choose';
}

/** Build the input_documents list for a chosen toggle position. */
export function documentsModeToInputDocuments(
  mode: DocumentsMode,
  chosen: string[],
): string[] {
  if (mode === 'all') return [ALL_INPUT_DOCUMENTS_TOKEN];
  if (mode === 'none') return [];
  return chosen.filter(
    (name) => name.trim() !== '' && name !== ALL_INPUT_DOCUMENTS_TOKEN,
  );
}

/** Strip a leading `agent.` / `agent['...']` wrapper to a bare variable name. */
export function stripAgentPrefix(templatePath: string): string {
  const trimmed = templatePath.trim();
  const bracketMatch = trimmed.match(/^agent\[(?:'|")(.*)(?:'|")\]$/);
  if (bracketMatch) {
    return bracketMatch[1].replace(/\\(['"\\])/g, '$1');
  }
  if (trimmed.startsWith('agent.')) {
    return trimmed.slice('agent.'.length);
  }
  return trimmed;
}

/**
 * Multiselect options of upstream document variables, stored as bare names.
 *
 * Only variables that carry artifact references at run time are offered
 * (`producesArtifact`): the uploaded `input_documents` and code-node outputs.
 * Plain agent/state TEXT outputs are excluded — the engine can't resolve them
 * to artifacts, so picking one appends the literal variable name and the node
 * hard-fails. The distinction is assigned upstream in `extractUpstreamVariables`
 * keyed on the producing node type.
 */
export function toDocumentVariableOptions(
  variables: WorkflowVariable[],
): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [];
  const seen = new Set<string>();
  for (const variable of variables) {
    if (!variable.producesArtifact) continue;

    const bareName = stripAgentPrefix(variable.templatePath);
    if (!bareName || seen.has(bareName)) continue;
    seen.add(bareName);
    options.push({ value: bareName, label: bareName });
  }
  return options;
}

/** Append a typed literal ref to a chosen list, ignoring blanks, the wildcard and duplicates. */
export function appendDocumentRef(chosen: string[], ref: string): string[] {
  const value = ref.trim();
  if (
    value === '' ||
    value === ALL_INPUT_DOCUMENTS_TOKEN ||
    chosen.includes(value)
  ) {
    return chosen;
  }
  return [...chosen, value];
}

/** Append stored chosen names lacking an upstream option so they stay visible and removable. */
export function withChosenDocumentOptions(
  options: { value: string; label: string }[],
  chosen: string[],
): { value: string; label: string }[] {
  const known = new Set(options.map((option) => option.value));
  const merged = [...options];
  for (const name of chosen) {
    const value = name.trim();
    if (!value || value === ALL_INPUT_DOCUMENTS_TOKEN || known.has(value)) {
      continue;
    }
    known.add(value);
    merged.push({ value, label: value });
  }
  return merged;
}
