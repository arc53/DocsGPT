import {
  applyPromptEdits,
  type PromptEdit,
  promptDiffSegments,
  promptDrafterMode,
  readPromptProposal,
} from './promptDraft';

const CONTENT = 'You answer questions.\nToday is Monday.\nBe brief.';
const EDITS: PromptEdit[] = [
  { id: 'e1', find: 'Today is Monday.\n', replace: '', reason: 'Date' },
  {
    id: 'e2',
    find: 'Be brief.',
    replace: 'Be brief. Never quote prices.',
    reason: 'Asked',
  },
];

describe('promptDrafterMode', () => {
  it('improves an existing prompt or a filled new one, writes an empty one', () => {
    expect(promptDrafterMode('EDIT', '')).toBe('improve');
    expect(promptDrafterMode('ADD', 'Some text')).toBe('improve');
    expect(promptDrafterMode('ADD', '  ')).toBe('write');
  });
});

describe('readPromptProposal', () => {
  it('reads an improve proposal and drops malformed edits', () => {
    const proposal = readPromptProposal({
      mode: 'improve',
      message: 'Done',
      edits: [...EDITS, { id: 'x' }, null],
      result: 'r',
      template_mode: { before: false, after: true },
      warnings: ['w', 3],
      checks: ['to_template', 'unknown'],
      suggestions: ['Add a hand-off', 4],
    });
    expect(proposal).toEqual({
      mode: 'improve',
      message: 'Done',
      edits: EDITS,
      result: 'r',
      templateMode: { before: false, after: true },
      warnings: ['w'],
      checks: ['to_template'],
      suggestions: ['Add a hand-off'],
    });
  });

  it('reads a write proposal', () => {
    expect(
      readPromptProposal({
        mode: 'write',
        message: 'Wrote',
        name: 'HR',
        content: 'You help.',
        reason: 'Persona',
        assumptions: ['Hand-offs go to HR.'],
      }),
    ).toEqual({
      mode: 'write',
      message: 'Wrote',
      name: 'HR',
      content: 'You help.',
      reason: 'Persona',
      warnings: [],
      checks: [],
      assumptions: ['Hand-offs go to HR.'],
      suggestions: [],
    });
  });

  it('rejects anything else', () => {
    expect(readPromptProposal(null)).toBeNull();
    expect(readPromptProposal({ mode: 'write', name: 'x' })).toBeNull();
    expect(readPromptProposal({ fields: {} })).toBeNull();
  });
});

describe('applyPromptEdits', () => {
  it('applies only the accepted edits', () => {
    expect(applyPromptEdits(CONTENT, EDITS, () => true)).toBe(
      'You answer questions.\nBe brief. Never quote prices.',
    );
    expect(applyPromptEdits(CONTENT, EDITS, (id) => id === 'e1')).toBe(
      'You answer questions.\nBe brief.',
    );
    expect(applyPromptEdits(CONTENT, EDITS, () => false)).toBe(CONTENT);
  });

  it('skips an edit whose text is gone', () => {
    const stale = [{ id: 'e9', find: 'Nope', replace: 'Yes', reason: '' }];
    expect(applyPromptEdits(CONTENT, stale, () => true)).toBe(CONTENT);
  });
});

describe('promptDiffSegments', () => {
  it('splits the text around each change, numbered in text order', () => {
    const segments = promptDiffSegments(CONTENT, [EDITS[1], EDITS[0]]);
    expect(segments).toEqual([
      { kind: 'text', text: 'You answer questions.\n' },
      { kind: 'change', edit: EDITS[0], number: 1 },
      { kind: 'change', edit: EDITS[1], number: 2 },
    ]);
  });
});
