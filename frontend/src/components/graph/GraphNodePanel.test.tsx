import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // "key:count", then any other params: "key:20 {"formatted":"20"}".
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts || !('count' in opts)) return key;
      const { count, ...rest } = opts;
      return Object.keys(rest).length
        ? `${key}:${count} ${JSON.stringify(rest)}`
        : `${key}:${count}`;
    },
  }),
}));

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
  useDispatch: () => dispatch,
}));

vi.mock('../../api/services/userService', () => ({
  default: { updateChunk: vi.fn() },
}));

import i18next from 'i18next';

import userService from '../../api/services/userService';
import { foldGraphTypes, type GraphNodeDetail } from '../graphViewUtils';
import { SidePanel } from '../ui/side-panel';
import GraphNodePanel, { RELATIONSHIP_PREVIEW } from './GraphNodePanel';

const updateChunk = (
  userService as unknown as {
    updateChunk: ReturnType<typeof vi.fn>;
  }
).updateChunk;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const fold = foldGraphTypes([
  { type: 'Company' },
  { type: 'Company' },
  { type: 'Person' },
  { type: 'Lane' },
]);

const DETAIL: GraphNodeDetail = {
  id: 'nord',
  name: 'Nordhaven Logistics B.V.',
  type: 'Company',
  description: 'Dutch road haulier based in Schiedam.',
  degree: 55,
  doc_freq: 20,
  relationships: [
    {
      id: 'anneke',
      name: 'Anneke de Vries',
      type: 'Person',
      degree: 40,
      edge_type: 'MANAGES',
      direction: 'in',
    },
    {
      id: 'anneke',
      name: 'Anneke de Vries',
      type: 'Person',
      degree: 40,
      edge_type: 'manages',
      direction: 'out',
    },
    {
      id: 'anneke',
      name: 'Anneke de Vries',
      type: 'Person',
      degree: 40,
      edge_type: 'CARRIER_MANAGER_FOR',
      direction: 'in',
    },
    {
      id: 'duisport',
      name: 'Duisport',
      type: 'Port',
      degree: 12,
      edge_type: null,
      direction: 'out',
    },
  ],
  chunks: [
    {
      chunk_id: 'c1',
      text: 'Carrier profile — Nordhaven Logistics B.V.',
      metadata: { source: 'inputs/local/Carrier_profile_Nordhaven.docx' },
    },
  ],
};

describe('GraphNodePanel', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    updateChunk.mockReset();
    dispatch.mockReset();
  });

  const render = async (
    props: Partial<React.ComponentProps<typeof GraphNodePanel>> = {},
  ) => {
    const handlers = {
      onClose: vi.fn(),
      onSelectNode: vi.fn(),
      onRetry: vi.fn(),
      onOpenInFiles: vi.fn(),
      onChunkSaved: vi.fn(),
    };
    await act(async () => {
      const { onClose, ...panelHandlers } = handlers;
      root.render(
        <SidePanel
          variant="docked"
          open
          onOpenChange={(open) => !open && onClose()}
        >
          <GraphNodePanel
            docId="doc"
            node={{ id: 'nord', name: 'Nordhaven', type: 'Company' }}
            detail={DETAIL}
            status="ready"
            fold={fold}
            {...panelHandlers}
            {...props}
          />
        </SidePanel>,
      );
    });
    return handlers;
  };

  const relationshipButtons = () =>
    Array.from(container.querySelectorAll('ul button'));

  it('shows the facts, one row per neighbour and the chunk file', async () => {
    await render();
    const text = container.textContent ?? '';
    expect(
      container.querySelector('[data-slot="panel-header"] h2')?.textContent,
    ).toBe('Nordhaven Logistics B.V.');
    expect(text).toContain('55');
    expect(text).toContain('settings.sources.graphrag.view.chunkCount:20');

    const rows = relationshipButtons();
    expect(rows).toHaveLength(2);
    // The busiest neighbour first, its labels normalised and deduplicated.
    expect(rows[0].textContent).toContain('Anneke de Vries');
    expect(rows[0].textContent).toContain('manages · carrier manager for');
    // No label on the edge: the "related to" fallback.
    expect(rows[1].textContent).toContain('Duisport');
    expect(rows[1].textContent).toContain(
      'settings.sources.graphrag.view.relatedTo',
    );

    expect(text).toContain('Carrier profile — Nordhaven Logistics B.V.');
    expect(text).toContain('Carrier_profile_Nordhaven.docx');
    expect(text).not.toContain('inputs/local');
  });

  it('closes from the side panel X', async () => {
    const { onClose } = await render();
    await act(async () => {
      (
        container.querySelector(
          'button[aria-label="sidePanel.close"]',
        ) as HTMLButtonElement
      ).click();
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('selects the neighbour a row points at', async () => {
    const { onSelectNode } = await render();
    await act(async () => {
      (relationshipButtons()[1] as HTMLButtonElement).click();
    });
    expect(onSelectNode).toHaveBeenCalledWith({
      id: 'duisport',
      name: 'Duisport',
      type: 'Port',
    });
  });

  it('shows the first rows and a Show all toggle for a busy node', async () => {
    const relationships = Array.from({ length: 15 }, (_, i) => ({
      id: `n${i}`,
      name: `Neighbour ${i}`,
      type: 'Person',
      degree: 30 - i,
      edge_type: 'knows',
    }));
    await render({ detail: { ...DETAIL, relationships } });
    expect(relationshipButtons()).toHaveLength(RELATIONSHIP_PREVIEW);
    const toggle = Array.from(container.querySelectorAll('button')).find(
      (b) =>
        b.textContent ===
        'settings.sources.graphrag.view.showAll:15 {"formatted":"15"}',
    )!;
    await act(async () => toggle.click());
    expect(relationshipButtons()).toHaveLength(15);
  });

  const relationshipsHeader = () =>
    Array.from(container.querySelectorAll('h4')).find((h) =>
      h.textContent?.startsWith('settings.sources.graphrag.view.relationships'),
    )!;
  const cappedNote = () =>
    Array.from(container.querySelectorAll('p')).find((p) =>
      p.textContent?.startsWith(
        'settings.sources.graphrag.view.relationshipsCapped',
      ),
    );

  // Bugs row 10: the backend caps the list; the header counts every edge and
  // a note says the list is partial.
  it('heads a capped list with the true total and says what it shows', async () => {
    await render({ detail: { ...DETAIL, relationships_total: 1204 } });
    expect(relationshipsHeader().textContent).toContain('1,204');
    const note = cappedNote();
    expect(note?.textContent).toBe(
      'settings.sources.graphrag.view.relationshipsCapped:1204 {"shown":"4","total":"1,204"}',
    );
    expect(note?.className).toContain('text-xs');
    expect(note?.className).toContain('text-muted-foreground');
  });

  it('adds no note when every relationship came back', async () => {
    await render({ detail: { ...DETAIL, relationships_total: 4 } });
    expect(relationshipsHeader().textContent).toContain('4');
    expect(cappedNote()).toBeUndefined();
  });

  it('counts the neighbour rows when the API sends no total', async () => {
    await render();
    expect(relationshipsHeader().textContent).toMatch(/2$/);
    expect(cappedNote()).toBeUndefined();
  });

  // Bugs row 8: counts in the app language, not the browser's.
  it('formats its counts in the app language', async () => {
    const language = i18next.language;
    i18next.language = 'de';
    try {
      await render({
        detail: { ...DETAIL, degree: 1234, doc_freq: 5678 },
      });
      const text = container.textContent ?? '';
      expect(text).toContain('1.234');
      expect(text).toContain(
        'settings.sources.graphrag.view.chunkCount:5678 {"formatted":"5.678"}',
      );
    } finally {
      i18next.language = language;
    }
  });

  it('offers Show more only for a long description', async () => {
    await render();
    expect(container.textContent).not.toContain(
      'settings.sources.graphrag.view.showMore',
    );
    await render({
      detail: { ...DETAIL, description: 'Long. '.repeat(60) },
    });
    expect(container.textContent).toContain(
      'settings.sources.graphrag.view.showMore',
    );
  });

  it('shows the known name while loading, and Retry on failure', async () => {
    await render({ detail: null, status: 'loading' });
    expect(
      container.querySelector('[data-slot="panel-header"] h2')?.textContent,
    ).toBe('Nordhaven');
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();

    const { onRetry } = await render({ detail: null, status: 'error' });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'settings.sources.graphrag.view.nodeLoadFailed',
    );
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(onRetry).toHaveBeenCalled();
  });

  const CHUNK_DETAIL: GraphNodeDetail = {
    ...DETAIL,
    chunks: [
      {
        chunk_id: 'c1',
        text: '# Account brief\n\nNordhaven Logistics B.V. hauls the Rotterdam lane.',
        metadata: {
          source: 'inputs/local/Account_brief.md',
          title: 'Account_brief.md',
          token_count: 1234,
        },
      },
    ],
  };

  const bodyButton = (text: string) =>
    [...document.body.querySelectorAll('button')].find(
      (b) => b.textContent === text,
    ) as HTMLButtonElement | undefined;

  const openTile = async () => {
    const tile = container.querySelector(
      '[data-slot="card"]',
    ) as HTMLButtonElement;
    expect(tile.tagName).toBe('BUTTON');
    await act(async () => tile.click());
  };

  const typeDraft = async (value: string) => {
    const field = document.body.querySelector('textarea')!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('previews a tile without markdown markers', async () => {
    await render({ detail: CHUNK_DETAIL });
    const tile = container.querySelector('[data-slot="card"]')!;
    expect(tile.textContent).toContain(
      'Account brief · Nordhaven Logistics B.V. hauls the Rotterdam lane.',
    );
    expect(tile.textContent).not.toContain('#');
  });

  it('opens a tile in the panel, with Back and the entity name marked', async () => {
    await render({ detail: CHUNK_DETAIL });
    await openTile();
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    const dialog = container.querySelector('[data-slot="side-panel"]')!;
    expect(
      dialog.querySelector('[aria-label="sidePanel.back"]'),
    ).not.toBeNull();
    expect(dialog.querySelector('h2')?.textContent).toBe('Account brief');
    expect(dialog.textContent).toContain(
      'settings.sources.graphrag.view.chunkMeta',
    );
    // The body renders the heading and marks the entity's name.
    const rendered = [...dialog.querySelectorAll('h1, h2, h3')].filter(
      (h) => h.textContent === 'Account brief',
    );
    expect(rendered).toHaveLength(2);
    expect(dialog.textContent).not.toContain('# Account brief');
    expect(dialog.querySelector('mark')?.textContent).toBe(
      'Nordhaven Logistics B.V.',
    );
  });

  it('opens the file on the Files tab and goes back to the node', async () => {
    const { onOpenInFiles, onClose } = await render({ detail: CHUNK_DETAIL });
    await openTile();
    await act(async () =>
      bodyButton('settings.sources.graphrag.view.openInFiles')!.click(),
    );
    expect(onOpenInFiles).toHaveBeenCalledWith('inputs/local/Account_brief.md');
    expect(container.querySelector('[aria-label="sidePanel.back"]')).toBeNull();
    // The node stays selected.
    expect(onClose).not.toHaveBeenCalled();
  });

  it('edits a chunk in the edit drawer, saves and refetches', async () => {
    updateChunk.mockResolvedValue({ ok: true, status: 200 });
    const { onChunkSaved } = await render({ detail: CHUNK_DETAIL });
    await openTile();
    await act(async () => bodyButton('modals.chunk.edit')!.click());
    expect(document.body.textContent).toContain(
      'settings.sources.graphrag.view.editChunk',
    );
    await typeDraft('# Account brief\n\nUpdated.');
    await act(async () => bodyButton('modals.chunk.save')!.click());
    expect(updateChunk).toHaveBeenCalledWith(
      {
        id: 'doc',
        chunk_id: 'c1',
        text: '# Account brief\n\nUpdated.',
        metadata: { title: 'Account_brief.md' },
      },
      'tok',
    );
    expect(onChunkSaved).toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({ variant: 'success' }),
      }),
    );
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    // Back on the node.
    expect(container.querySelector('[aria-label="sidePanel.back"]')).toBeNull();
  });

  it('keeps the edit drawer open with an alert when the save fails', async () => {
    updateChunk.mockResolvedValue({ ok: false, status: 500 });
    const { onChunkSaved } = await render({ detail: CHUNK_DETAIL });
    await openTile();
    await act(async () => bodyButton('modals.chunk.edit')!.click());
    await typeDraft('Changed');
    await act(async () => bodyButton('modals.chunk.save')!.click());
    const dialog = document.body.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector('[role="alert"]')?.textContent).toBe(
      'settings.sources.chunkErrors.save',
    );
    expect(document.body.querySelector('textarea')?.value).toBe('Changed');
    expect(onChunkSaved).not.toHaveBeenCalled();
  });

  it('falls back to the overview links when the detail has no relationships', async () => {
    const overview = {
      nodes: [
        {
          id: 'nord',
          name: 'Nordhaven Logistics B.V.',
          type: 'Company',
          degree: 2,
        },
        { id: 'duisport', name: 'Duisport', type: 'Port', degree: 7 },
        { id: 'marta', name: 'Marta Keller', type: 'Person', degree: 3 },
        { id: 'far', name: 'Far away', type: 'Port', degree: 1 },
      ],
      links: [
        { source: 'nord', target: 'duisport', type: 'SHIPS_VIA' },
        { source: 'marta', target: 'nord', type: 'manages' },
        { source: 'marta', target: 'far', type: 'visits' },
      ],
    };
    await render({
      detail: { ...DETAIL, relationships: undefined },
      overview,
    });
    const rows = relationshipButtons();
    expect(rows.map((row) => row.textContent)).toEqual([
      'Duisportships via',
      'Marta Kellermanages',
    ]);
    expect(container.textContent).not.toContain(
      'settings.sources.graphrag.view.noRelationships',
    );

    await render({ detail: { ...DETAIL, relationships: undefined } });
    expect(container.textContent).toContain(
      'settings.sources.graphrag.view.noRelationships',
    );
  });
});
