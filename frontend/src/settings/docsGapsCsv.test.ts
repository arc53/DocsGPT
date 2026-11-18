import { describe, expect, it } from 'vitest';

import {
  csvCell,
  DOCS_GAPS_CSV_HEADER,
  docsGapsCsv,
  docsGapsFileName,
} from './docsGapsCsv';
import type { DocsGapRow } from './types';

const row = (overrides: Partial<DocsGapRow> = {}): DocsGapRow => ({
  key: '/install/docker',
  name: 'Installing on Docker',
  source: 'Core docs',
  expected_gaps: 6.2,
  turns: 31,
  rate: 0.2,
  low: 0.11,
  high: 0.33,
  previous_expected: 4,
  examples: [
    {
      message_id: 'm1',
      conversation_id: 'c1',
      prompt: 'How do I set the port?',
      p: 0.91,
      timestamp: '2026-10-19T10:00:00Z',
    },
    {
      message_id: 'm2',
      conversation_id: 'c2',
      prompt: 'Port, please',
      p: 0.8,
      timestamp: '2026-10-19T11:00:00Z',
    },
  ],
  ...overrides,
});

const parse = (csv: string) => csv.replace(/^\uFEFF/, '').split('\r\n');

describe('docsGapsCsv', () => {
  it('starts with a BOM and the machine-key header, rows CRLF-separated', () => {
    const csv = docsGapsCsv([row()], 'page');
    expect(csv.startsWith('\uFEFF')).toBe(true);
    expect(csv.endsWith('\r\n')).toBe(true);
    const [header, line] = parse(csv);
    expect(header).toBe(DOCS_GAPS_CSV_HEADER.join(','));
    expect(header).toBe(
      'group,key,name,source,gaps,gaps_low,gaps_high,questions,share,share_low,share_high,previous_gaps,example_questions',
    );
    // Unformatted numbers; the ranges are the share's bounds times questions.
    expect(line).toBe(
      'page,/install/docker,Installing on Docker,Core docs,6.2,3.41,10.23,31,0.2,0.11,0.33,4,"How do I set the port? | Port, please"',
    );
  });

  it('keeps a group with no key as an empty cell', () => {
    const [, line] = parse(docsGapsCsv([row({ key: null })], 'source'));
    expect(line.startsWith('source,,')).toBe(true);
  });

  it('defuses cells a spreadsheet would run as a formula', () => {
    expect(csvCell('=HYPERLINK("x")')).toBe(`"'=HYPERLINK(""x"")"`);
    expect(csvCell('+1')).toBe("'+1");
    expect(csvCell('-2')).toBe("'-2");
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvCell('\tcmd')).toBe("'\tcmd");
    expect(csvCell('\rcmd')).toBe(`"'\rcmd"`);
    expect(csvCell('plain')).toBe('plain');
    const [, line] = parse(
      docsGapsCsv(
        [
          row({
            examples: [{ ...row().examples[0], prompt: '=cmd|"/C calc"!A0' }],
          }),
        ],
        'page',
      ),
    );
    expect(line.endsWith(`"'=cmd|""/C calc""!A0"`)).toBe(true);
  });

  it('quotes commas, quotes and line breaks', () => {
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('two\nlines')).toBe('"two\nlines"');
  });
});

describe('docsGapsFileName', () => {
  const date = new Date(2026, 9, 19);
  it('names the agent, the grouping, the window and the day', () => {
    expect(
      docsGapsFileName({
        agentName: 'Fintech Bot (EU)',
        groupBy: 'topic',
        filterOption: 'last_30_days',
        date,
      }),
    ).toBe('docs-gaps-fintech-bot-eu-topic-last_30_days-2026-10-19.csv');
  });

  it('says all for the account, and keeps non-Latin names', () => {
    expect(
      docsGapsFileName({ groupBy: 'page', filterOption: 'last_7_days', date }),
    ).toBe('docs-gaps-all-page-last_7_days-2026-10-19.csv');
    expect(
      docsGapsFileName({
        agentName: 'Помощник',
        groupBy: 'page',
        filterOption: 'last_7_days',
        date,
      }),
    ).toBe('docs-gaps-помощник-page-last_7_days-2026-10-19.csv');
    expect(
      docsGapsFileName({
        agentName: '!!!',
        groupBy: 'page',
        filterOption: 'last_7_days',
        date,
      }),
    ).toBe('docs-gaps-agent-page-last_7_days-2026-10-19.csv');
  });
});
