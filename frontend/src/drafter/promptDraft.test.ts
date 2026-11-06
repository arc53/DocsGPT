import {
  applyPromptEdits,
  fittingEdits,
  type PromptEdit,
  promptAsRead,
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
  // The server refuses to improve no text, saved prompt or not.
  it('improves a prompt with text and writes an empty one', () => {
    expect(promptDrafterMode('Some text')).toBe('improve');
    expect(promptDrafterMode('')).toBe('write');
    expect(promptDrafterMode('  ')).toBe('write');
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

describe('fittingEdits', () => {
  it('keeps the edits whose text occurs once and that overlap no earlier one', () => {
    const edits: PromptEdit[] = [
      { id: 'e1', find: 'Be brief.', replace: 'Be short.', reason: 'r' },
      { id: 'e2', find: 'Gone.', replace: 'x', reason: 'r' },
      { id: 'e3', find: 'e', replace: 'x', reason: 'r' },
      { id: 'e4', find: 'brief', replace: 'short', reason: 'r' },
    ];
    expect(fittingEdits(CONTENT, edits).map((edit) => edit.id)).toEqual(['e1']);
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

// The server reads the text cleaned of invisible and control characters, so
// its edits' text has none; they map back onto the text as it is.
describe('edits on a text with invisible characters', () => {
  const ZWSP = '\u200b';
  const TEXT = `Be${ZWSP} brief.\r\nAlways cite.${ZWSP}\u0007 Thanks.`;
  const edit = (find: string, replace: string): PromptEdit => ({
    id: 'e1',
    find,
    replace,
    reason: 'r',
  });

  it('reads the text as the server does', () => {
    expect(promptAsRead(TEXT)).toBe('Be brief.\nAlways cite. Thanks.');
    expect(promptAsRead(`  ${ZWSP}Hi\u202e there\ufeff \n`)).toBe('Hi there');
    // Tag characters go, except a subdivision flag's; joiners stay.
    const wales =
      '\u{1F3F4}\u{E0067}\u{E0062}\u{E0077}\u{E006C}\u{E0073}\u{E007F}';
    const family = '\u{1F468}\u200d\u{1F469}\u200d\u{1F467}';
    expect(promptAsRead(`a\u{E0041}\u{E0042}b ${wales} ${family}`)).toBe(
      `ab ${wales} ${family}`,
    );
  });

  it('applies an edit whose text spans one, replacing it with the passage', () => {
    const edits = [edit('Be brief.', 'Be short.')];
    expect(fittingEdits(TEXT, edits)).toEqual(edits);
    expect(applyPromptEdits(TEXT, edits, () => true)).toBe(
      `Be short.\r\nAlways cite.${ZWSP}\u0007 Thanks.`,
    );
    // Rejected, the passage stays exactly as it was.
    expect(applyPromptEdits(TEXT, edits, () => false)).toBe(TEXT);
  });

  it('keeps the ones outside an edit, line ends included', () => {
    const edits = [edit('Always cite.', 'Cite sources.')];
    expect(fittingEdits(TEXT, edits)).toEqual(edits);
    expect(applyPromptEdits(TEXT, edits, () => true)).toBe(
      `Be${ZWSP} brief.\r\nCite sources.${ZWSP}\u0007 Thanks.`,
    );
    expect(promptDiffSegments(TEXT, edits)).toEqual([
      { kind: 'text', text: `Be${ZWSP} brief.\r\n` },
      { kind: 'change', edit: edits[0], number: 1 },
      { kind: 'text', text: `${ZWSP}\u0007 Thanks.` },
    ]);
  });

  it('applies an edit across a line end the server read as \\n', () => {
    const edits = [edit('brief.\nAlways', 'brief. Always')];
    expect(applyPromptEdits(TEXT, edits, () => true)).toBe(
      `Be${ZWSP} brief. Always cite.${ZWSP}\u0007 Thanks.`,
    );
  });
});
