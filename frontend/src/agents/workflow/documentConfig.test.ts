import { describe, expect, it } from 'vitest';

import type { WorkflowVariable } from './components/PromptTextArea';
import {
  ALL_INPUT_DOCUMENTS_TOKEN,
  appendDocumentRef,
  DEFAULT_FILE_PASSING,
  documentsModeToInputDocuments,
  getDocumentsMode,
  normalizeFilePassing,
  stripAgentPrefix,
  toDocumentVariableOptions,
  withChosenDocumentOptions,
} from './documentConfig';

describe('getDocumentsMode', () => {
  it('treats missing/empty as none', () => {
    expect(getDocumentsMode(undefined)).toBe('none');
    expect(getDocumentsMode([])).toBe('none');
  });

  it('treats the wildcard token as all', () => {
    expect(getDocumentsMode([ALL_INPUT_DOCUMENTS_TOKEN])).toBe('all');
  });

  it('treats a bare-name list as choose', () => {
    expect(getDocumentsMode(['wire_doc'])).toBe('choose');
    expect(getDocumentsMode(['wire_doc', 'A1'])).toBe('choose');
  });
});

describe('documentsModeToInputDocuments', () => {
  it('maps all to the wildcard token regardless of chosen names', () => {
    expect(documentsModeToInputDocuments('all', ['wire_doc'])).toEqual([
      ALL_INPUT_DOCUMENTS_TOKEN,
    ]);
  });

  it('maps none to an empty list', () => {
    expect(documentsModeToInputDocuments('none', ['wire_doc'])).toEqual([]);
  });

  it('maps choose to the chosen bare names, dropping blanks and the wildcard', () => {
    expect(
      documentsModeToInputDocuments('choose', [
        'wire_doc',
        '  ',
        ALL_INPUT_DOCUMENTS_TOKEN,
        'A1',
      ]),
    ).toEqual(['wire_doc', 'A1']);
  });

  it('round-trips a chosen selection through getDocumentsMode', () => {
    const next = documentsModeToInputDocuments('choose', ['wire_doc']);
    expect(getDocumentsMode(next)).toBe('choose');
    expect(next).toEqual(['wire_doc']);
  });
});

describe('normalizeFilePassing', () => {
  it('passes through supported values', () => {
    expect(normalizeFilePassing('auto')).toBe('auto');
    expect(normalizeFilePassing('native')).toBe('native');
    expect(normalizeFilePassing('extract')).toBe('extract');
  });

  it('falls back to the default for unknown values', () => {
    expect(normalizeFilePassing(undefined)).toBe(DEFAULT_FILE_PASSING);
    expect(normalizeFilePassing('bogus')).toBe(DEFAULT_FILE_PASSING);
  });
});

describe('stripAgentPrefix', () => {
  it('strips a dotted agent prefix to a bare name', () => {
    expect(stripAgentPrefix('agent.wire_doc')).toBe('wire_doc');
    expect(stripAgentPrefix('agent.node_abc_output')).toBe('node_abc_output');
  });

  it('strips a bracketed agent prefix and unescapes quotes', () => {
    expect(stripAgentPrefix("agent['weird name']")).toBe('weird name');
    expect(stripAgentPrefix("agent['it\\'s']")).toBe("it's");
  });

  it('leaves bare names untouched', () => {
    expect(stripAgentPrefix('A1')).toBe('A1');
  });
});

describe('toDocumentVariableOptions', () => {
  const make = (
    templatePath: string,
    producesArtifact = false,
  ): WorkflowVariable => ({
    label: templatePath,
    templatePath,
    section: 'x',
    producesArtifact,
  });

  it('offers only artifact-producing variables (input_documents, code outputs)', () => {
    const options = toDocumentVariableOptions([
      make('agent.input_documents', true),
      make('agent.node_code1_output', true),
      make("agent['weird name']", true),
    ]);
    expect(options).toEqual([
      { value: 'input_documents', label: 'input_documents' },
      { value: 'node_code1_output', label: 'node_code1_output' },
      { value: 'weird name', label: 'weird name' },
    ]);
  });

  it('excludes plain agent/state TEXT outputs that are not artifact refs', () => {
    const options = toDocumentVariableOptions([
      make('agent.node_agent1_output'),
      make('agent.some_state_var'),
      make('agent.query'),
      make('agent.chat_history'),
      make('source.content'),
      make('system.date'),
      make('artifacts.artifact(id)'),
    ]);
    expect(options).toEqual([]);
  });

  it('deduplicates by bare name', () => {
    const options = toDocumentVariableOptions([
      make('agent.wire_doc', true),
      make('agent.wire_doc', true),
    ]);
    expect(options).toEqual([{ value: 'wire_doc', label: 'wire_doc' }]);
  });
});

describe('appendDocumentRef', () => {
  it('appends a trimmed literal ref', () => {
    expect(appendDocumentRef(['wire_doc'], '  A1 ')).toEqual([
      'wire_doc',
      'A1',
    ]);
  });

  it('ignores blanks and the wildcard token', () => {
    expect(appendDocumentRef(['wire_doc'], '   ')).toEqual(['wire_doc']);
    expect(appendDocumentRef(['wire_doc'], ALL_INPUT_DOCUMENTS_TOKEN)).toEqual([
      'wire_doc',
    ]);
  });

  it('does not append an already-present ref', () => {
    expect(appendDocumentRef(['A1'], 'A1')).toEqual(['A1']);
  });
});

describe('withChosenDocumentOptions', () => {
  const base = [{ value: 'wire_doc', label: 'wire_doc' }];

  it('keeps known options unchanged when all chosen are present', () => {
    expect(withChosenDocumentOptions(base, ['wire_doc'])).toEqual(base);
  });

  it('appends an orphaned chosen name (renamed/deleted upstream var) as removable', () => {
    expect(
      withChosenDocumentOptions(base, ['wire_doc', 'renamed_doc']),
    ).toEqual([
      { value: 'wire_doc', label: 'wire_doc' },
      { value: 'renamed_doc', label: 'renamed_doc' },
    ]);
  });

  it('surfaces a literal ref that has no upstream option', () => {
    expect(withChosenDocumentOptions([], ['A1'])).toEqual([
      { value: 'A1', label: 'A1' },
    ]);
  });

  it('ignores blanks and the wildcard token', () => {
    expect(
      withChosenDocumentOptions(base, ['', ' ', ALL_INPUT_DOCUMENTS_TOKEN]),
    ).toEqual(base);
  });

  it('does not duplicate an already-known chosen name', () => {
    expect(withChosenDocumentOptions(base, ['wire_doc', 'wire_doc'])).toEqual(
      base,
    );
  });
});
