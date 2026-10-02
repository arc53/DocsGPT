import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'tokens' in opts ? `${key}:${opts.tokens}` : key,
  }),
}));

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

const state = {
  preference: {
    token: 'tok',
    sourceDocs: [
      { id: 'src-1', name: 'Policies library', date: '', model: '' },
    ],
  },
};
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: typeof state) => unknown) => selector(state),
}));

vi.mock('../api/services/userService', () => ({
  default: { getSourceChunk: vi.fn(), getDocumentChunks: vi.fn() },
}));

import userService from '../api/services/userService';
import { SidePanel } from '../components/ui/side-panel';
import type { AnswerSource } from './chatCompanion';
import CitationReader from './CitationReader';

const service = userService as unknown as {
  getSourceChunk: ReturnType<typeof vi.fn>;
  getDocumentChunks: ReturnType<typeof vi.fn>;
};

const json = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  });

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const FILE: AnswerSource = {
  title: 'Leave policy.docx',
  text: 'Staff accrue 25 days...',
  source: 'Leave_policy.docx',
  source_id: 'src-1',
  chunk_key: 'a'.repeat(32),
};

const CHUNK = {
  success: true,
  chunk: {
    doc_id: '7',
    text: 'Staff accrue 25 days of **annual leave**.',
    metadata: { source: 'hr/Leave_policy.docx', token_count: 12 },
  },
  source: {
    id: 'src-1',
    name: 'HR handbook',
    type: 'local',
    kind: 'classic',
    date: '2026-09-01T12:00:00',
    access: 'viewer',
    allowed_actions: ['use'],
  },
  page_path: null,
};

describe('CitationReader', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getSourceChunk.mockReset();
    service.getDocumentChunks.mockReset();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (source: AnswerSource, onBack = vi.fn()) => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <SidePanel variant="docked" open onOpenChange={vi.fn()}>
            <CitationReader source={source} number={2} onBack={onBack} />
          </SidePanel>
        </MemoryRouter>,
      );
    });
    return onBack;
  };

  const header = () => container.querySelector('[data-slot="panel-header"]')!;
  const body = () => container.querySelector('[data-slot="panel-body"]')!;
  const button = (text: string) =>
    [...container.querySelectorAll('button')].find(
      (b) => b.textContent === text,
    );

  it('shows the full passage, rendered, with what is known about it', async () => {
    service.getSourceChunk.mockReturnValue(json(200, CHUNK));
    await render(FILE);

    expect(service.getSourceChunk).toHaveBeenCalledWith(
      'src-1',
      'a'.repeat(32),
      'tok',
    );
    expect(header().querySelector('h2')?.textContent).toBe('Leave policy.docx');
    expect(header().textContent).toContain('HR handbook');
    // The number the answer cited it by, as a badge.
    expect(header().querySelector('[data-slot="badge"]')?.textContent).toBe(
      '2',
    );
    expect(body().querySelector('strong')?.textContent).toBe('annual leave');
    const rows = [...body().querySelectorAll('dt')].map((dt) => dt.textContent);
    expect(rows).toEqual([
      'conversation.sources.reader.knowledge',
      'conversation.sources.reader.file',
      'conversation.sources.reader.added',
      'conversation.sources.reader.length',
    ]);
    expect(body().textContent).toContain('hr/Leave_policy.docx');
    expect(body().textContent).toContain(
      'conversation.sources.reader.tokens:12',
    );
    expect(body().querySelector('[role="note"]')).toBeNull();
  });

  it('goes back to the list from the header arrow', async () => {
    service.getSourceChunk.mockReturnValue(json(200, CHUNK));
    const onBack = await render(FILE);
    const back = header().querySelector<HTMLButtonElement>(
      'button[aria-label="conversation.sources.reader.back"]',
    );
    await act(async () => back!.click());
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('shows the excerpt with a note for an answer saved without chunk keys', async () => {
    await render({
      title: 'Old.pdf',
      text: 'An excerpt saved long ago',
      source: 'Old.pdf',
    });
    expect(service.getSourceChunk).not.toHaveBeenCalled();
    expect(body().querySelector('[role="note"]')?.textContent).toContain(
      'conversation.sources.reader.excerptOnly',
    );
    expect(body().textContent).toContain('An excerpt saved long ago');
  });

  it('finds a re-chunked passage by its excerpt', async () => {
    service.getSourceChunk.mockReturnValue(
      json(404, { message: 'Chunk not found' }),
    );
    service.getDocumentChunks.mockReturnValue(
      json(200, {
        chunks: [
          { doc_id: '9', text: 'Staff accrue 25 days, revised.', metadata: {} },
        ],
      }),
    );
    await render(FILE);

    expect(service.getDocumentChunks).toHaveBeenCalledWith(
      'src-1',
      1,
      1,
      'tok',
      undefined,
      'Staff accrue 25 days',
    );
    expect(body().textContent).toContain('Staff accrue 25 days, revised.');
    // The name comes from the knowledge list the app already holds.
    expect(header().textContent).toContain('Policies library');
    expect(body().querySelector('[role="note"]')).toBeNull();
  });

  it('says the passage is gone when the excerpt finds nothing either', async () => {
    service.getSourceChunk.mockReturnValue(
      json(404, { message: 'Chunk not found' }),
    );
    service.getDocumentChunks.mockReturnValue(json(200, { chunks: [] }));
    await render(FILE);
    expect(body().querySelector('[role="note"]')?.textContent).toContain(
      'conversation.sources.reader.missing',
    );
    expect(body().textContent).toContain('Staff accrue 25 days');
  });

  it.each([
    [403, { message: 'Forbidden' }],
    [404, { message: 'Source not found' }],
  ])(
    'falls back to the excerpt when the source is out of reach (%s)',
    async (status, payload) => {
      service.getSourceChunk.mockReturnValue(json(status, payload));
      await render(FILE);
      expect(service.getDocumentChunks).not.toHaveBeenCalled();
      expect(body().querySelector('[role="note"]')?.textContent).toContain(
        'conversation.sources.reader.forbidden',
      );
    },
  );

  it('offers a retry when the load fails', async () => {
    service.getSourceChunk.mockReturnValueOnce(json(500, {}));
    await render(FILE);
    expect(body().textContent).toContain(
      'conversation.sources.reader.loadFailed',
    );

    service.getSourceChunk.mockReturnValueOnce(json(200, CHUNK));
    await act(async () => button('retry')?.click());
    expect(service.getSourceChunk).toHaveBeenCalledTimes(2);
    expect(body().querySelector('strong')?.textContent).toBe('annual leave');
  });

  it('opens a web source in a new tab from the footer', async () => {
    service.getSourceChunk.mockReturnValue(json(200, CHUNK));
    await render({
      ...FILE,
      title: 'Pricing',
      source: 'https://example.com/pricing',
    });
    const link = container.querySelector<HTMLAnchorElement>(
      '[data-slot="panel-footer"] a',
    );
    expect(link?.getAttribute('href')).toBe('https://example.com/pricing');
    expect(link?.getAttribute('target')).toBe('_blank');
    expect(link?.getAttribute('rel')).toBe('noopener noreferrer');
    const rows = [...body().querySelectorAll('dt')].map((dt) => dt.textContent);
    expect(rows).toContain('conversation.sources.reader.link');
  });

  it('labels a wiki chunk with its page', async () => {
    service.getSourceChunk.mockReturnValue(
      json(200, {
        ...CHUNK,
        source: { ...CHUNK.source, kind: 'wiki' },
        chunk: { ...CHUNK.chunk, metadata: { source: '/guide/leave.md' } },
        page_path: '/guide/leave.md',
      }),
    );
    await render(FILE);
    const rows = [...body().querySelectorAll('dt')].map((dt) => dt.textContent);
    expect(rows).toContain('conversation.sources.reader.page');
    expect(body().textContent).toContain('/guide/leave.md');
  });
});

describe('CitationReader › Open in Knowledge', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    service.getSourceChunk.mockReset();
    service.getDocumentChunks.mockReset();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (source: AnswerSource) => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <SidePanel variant="docked" open onOpenChange={vi.fn()}>
            <CitationReader source={source} number={1} onBack={vi.fn()} />
          </SidePanel>
        </MemoryRouter>,
      );
    });
  };

  const knowledgeLink = () => {
    const anchor = [
      ...container.querySelectorAll<HTMLAnchorElement>(
        '[data-slot="panel-footer"] a',
      ),
    ].find(
      (a) => a.textContent === 'conversation.sources.reader.openInKnowledge',
    );
    return anchor ? new URL(anchor.getAttribute('href')!, 'http://x') : null;
  };

  it('links the chunk, found by its excerpt, in its file', async () => {
    service.getSourceChunk.mockReturnValue(json(200, CHUNK));
    await render(FILE);
    const url = knowledgeLink()!;
    expect(url.pathname).toBe('/settings/knowledge');
    expect(url.searchParams.get('source')).toBe('src-1');
    expect(url.searchParams.get('chunk')).toBe('7');
    expect(url.searchParams.get('q')).toBe('Staff accrue 25 days');
    expect(url.searchParams.get('path')).toBe('hr/Leave_policy.docx');
  });

  it('links a wiki chunk by its page', async () => {
    service.getSourceChunk.mockReturnValue(
      json(200, {
        ...CHUNK,
        source: { ...CHUNK.source, kind: 'wiki' },
        page_path: 'guide/leave.md',
      }),
    );
    await render(FILE);
    const url = knowledgeLink()!;
    expect(url.searchParams.get('wikiPage')).toBe('guide/leave.md');
    expect(url.searchParams.get('chunk')).toBeNull();
  });

  it('links a re-chunked passage of a source in the knowledge list', async () => {
    service.getSourceChunk.mockReturnValue(
      json(404, { message: 'Chunk not found' }),
    );
    service.getDocumentChunks.mockReturnValue(
      json(200, {
        chunks: [{ doc_id: '9', text: 'Staff accrue 25 days.', metadata: {} }],
      }),
    );
    await render(FILE);
    expect(knowledgeLink()?.searchParams.get('chunk')).toBe('9');
  });

  const anchorByText = (text: string) =>
    [...container.querySelectorAll<HTMLAnchorElement>('a')].find(
      (a) => a.textContent === text,
    );

  it('links the knowledge name back to the source', async () => {
    service.getSourceChunk.mockReturnValue(json(200, CHUNK));
    await render(FILE);
    const url = new URL(
      anchorByText('HR handbook')!.getAttribute('href')!,
      'http://x',
    );
    expect(url.pathname).toBe('/settings/knowledge');
    expect([...url.searchParams.keys()]).toEqual(['source']);
    expect(url.searchParams.get('source')).toBe('src-1');
  });

  it("opens a wiki passage's page links in Knowledge, web links in a new tab", async () => {
    service.getSourceChunk.mockReturnValue(
      json(200, {
        ...CHUNK,
        source: { ...CHUNK.source, kind: 'wiki' },
        chunk: {
          ...CHUNK.chunk,
          text: 'See [runbook](../engineering/runbook.md) and [site](https://arc53.com).',
          metadata: { source: '/people/leave.md' },
        },
        page_path: '/people/leave.md',
      }),
    );
    await render(FILE);
    const runbook = new URL(
      anchorByText('runbook')!.getAttribute('href')!,
      'http://x',
    );
    expect(runbook.searchParams.get('wikiPage')).toBe('engineering/runbook.md');
    expect(anchorByText('runbook')!.getAttribute('target')).toBeNull();
    expect(anchorByText('site')!.getAttribute('target')).toBe('_blank');
  });

  it("leaves a wiki excerpt's links and the name as text when the source is out of reach", async () => {
    service.getSourceChunk.mockReturnValue(json(403, {}));
    await render({
      ...FILE,
      source_id: 'other',
      source: '/people/leave.md',
      text: 'See [runbook](/engineering/runbook.md)...',
    });
    expect(anchorByText('runbook')).toBeUndefined();
    expect(container.textContent).toContain('See runbook');
  });

  it('offers no link when only the excerpt is shown', async () => {
    service.getSourceChunk.mockReturnValue(json(403, {}));
    await render(FILE);
    expect(knowledgeLink()).toBeNull();
    expect(container.querySelector('[data-slot="panel-footer"]')).toBeNull();
  });
});
