import {
  artifactKind,
  cardsFromRunArtifacts,
  cardsFromToolCalls,
  orderArtifactCards,
  type ArtifactCardItem,
} from './artifactCards';
import type { ToolCallsType } from './types';

const call = (overrides: Partial<ToolCallsType>): ToolCallsType => ({
  tool_name: 'code_executor',
  action_name: 'run_code',
  call_id: 'c1',
  arguments: {},
  status: 'completed',
  ...overrides,
});

describe('artifactKind', () => {
  it('reads the kind from the file extension', () => {
    expect(artifactKind({ filename: 'report.html' })).toBe('page');
    expect(artifactKind({ filename: 'QBR.PDF' })).toBe('pdf');
    expect(artifactKind({ filename: 'deck.pptx' })).toBe('slides');
    expect(artifactKind({ filename: 'terms.docx' })).toBe('document');
    expect(artifactKind({ filename: 'model.xlsx' })).toBe('spreadsheet');
    expect(artifactKind({ filename: 'export.csv' })).toBe('data');
    expect(artifactKind({ filename: 'chart.png' })).toBe('image');
    expect(artifactKind({ filename: 'archive.zip' })).toBe('file');
  });

  // A generated file's name is the model's to pick; an inherited property is
  // no kind (the card would have no icon to render).
  it('ignores an extension that names an object property', () => {
    expect(artifactKind({ filename: 'output.constructor' })).toBe('file');
    expect(artifactKind({ filename: 'x.__proto__' })).toBe('file');
    expect(artifactKind({ filename: 'x.toString' })).toBe('file');
    expect(artifactKind({ filename: 'x.hasOwnProperty' })).toBe('file');
  });

  it('falls back to the mime type when the name has no known extension', () => {
    expect(artifactKind({ filename: 'out', mimeType: 'application/pdf' })).toBe(
      'pdf',
    );
    expect(artifactKind({ mimeType: 'image/svg+xml' })).toBe('image');
  });

  // Notes and todos are legacy artifacts with no file; the tool says which.
  it('names a note, todo or memory by the tool that made it', () => {
    expect(artifactKind({ toolName: 'notes' })).toBe('note');
    expect(artifactKind({ toolName: 'todo_list' })).toBe('todo');
    expect(artifactKind({ toolName: 'memory' })).toBe('memory');
  });
});

describe('cardsFromToolCalls', () => {
  it('prefers the title, keeps the version, and downloads only files', () => {
    const cards = cardsFromToolCalls([
      call({
        artifacts: [
          {
            id: 'a1',
            filename: 'Q3_Review.pptx',
            ref: 'A1',
            title: 'Q3 Support Review',
            version: 2,
          },
          { id: 'a2', filename: 'claims.csv', ref: 'A2' },
        ],
      }),
      call({ call_id: 'c2', tool_name: 'notes', artifact_id: 'n1' }),
    ]);
    expect(cards).toEqual([
      {
        id: 'a1',
        title: 'Q3 Support Review',
        kind: 'slides',
        version: 2,
        filename: 'Q3_Review.pptx',
        toolName: 'code_executor',
        downloadable: true,
      },
      {
        id: 'a2',
        title: 'claims.csv',
        kind: 'data',
        version: undefined,
        filename: 'claims.csv',
        toolName: 'code_executor',
        downloadable: true,
      },
      {
        id: 'n1',
        title: 'Notes',
        kind: 'note',
        version: undefined,
        filename: undefined,
        toolName: 'notes',
        downloadable: false,
      },
    ]);
  });
});

describe('cardsFromRunArtifacts', () => {
  it('maps a run list entry, titled by its title or file', () => {
    expect(
      cardsFromRunArtifacts([
        {
          id: 'r1',
          kind: 'document',
          title: 'Q3 QBR',
          current_version: 1,
          filename: 'qbr.html',
          mime_type: 'text/html',
        },
        {
          id: 'r2',
          kind: 'document',
          title: null,
          current_version: 3,
          filename: 'qbr.pdf',
          mime_type: 'application/pdf',
        },
      ]),
    ).toEqual([
      {
        id: 'r1',
        title: 'Q3 QBR',
        kind: 'page',
        version: 1,
        filename: 'qbr.html',
        toolName: '',
        downloadable: true,
      },
      {
        id: 'r2',
        title: 'qbr.pdf',
        kind: 'pdf',
        version: 3,
        filename: 'qbr.pdf',
        toolName: '',
        downloadable: true,
      },
    ]);
  });

  // The version row is missing: there is no file to name or save.
  it('names a file-less artifact by the given fallback and offers no download', () => {
    const [card] = cardsFromRunArtifacts(
      [
        {
          id: 'abcdef123456',
          kind: 'document',
          title: null,
          current_version: null,
          filename: null,
          mime_type: null,
        },
      ],
      (id) => `Artifact ${id}`,
    );
    expect(card.title).toBe('Artifact abcdef12');
    expect(card.downloadable).toBe(false);
  });
});

describe('orderArtifactCards', () => {
  const card = (id: string, kind: ArtifactCardItem['kind']) =>
    ({ id, title: id, kind, toolName: '', downloadable: true }) as const;

  it('puts documents first, then images, then data and other files, each in produced order', () => {
    const ordered = orderArtifactCards([
      card('chart', 'image'),
      card('raw', 'data'),
      card('deck', 'slides'),
      card('zip', 'file'),
      card('report', 'pdf'),
      card('chart2', 'image'),
    ]);
    expect(ordered.map((c) => c.id)).toEqual([
      'deck',
      'report',
      'chart',
      'chart2',
      'raw',
      'zip',
    ]);
  });

  it('keeps one card per artifact', () => {
    expect(
      orderArtifactCards([card('a', 'pdf'), card('a', 'pdf')]).map((c) => c.id),
    ).toEqual(['a']);
  });
});
