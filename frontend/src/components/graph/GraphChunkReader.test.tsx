import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
  useDispatch: () => dispatch,
}));

vi.mock('../../api/services/userService', () => ({
  default: { updateChunk: vi.fn() },
}));

import userService from '../../api/services/userService';
import type { GraphNodeChunk } from '../graphViewUtils';
import { SidePanel } from '../ui/side-panel';
import GraphChunkReader from './GraphChunkReader';

const updateChunk = (
  userService as unknown as { updateChunk: ReturnType<typeof vi.fn> }
).updateChunk;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('GraphChunkReader', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    updateChunk.mockReset();
    updateChunk.mockResolvedValue({ ok: true, status: 200 });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    dispatch.mockReset();
  });

  const button = (text: string) =>
    [...document.body.querySelectorAll('button')].find(
      (b) => b.textContent === text,
    ) as HTMLButtonElement | undefined;

  const saveEdit = async (chunk: GraphNodeChunk, value: string) => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <GraphChunkReader
            docId="doc"
            chunk={chunk}
            highlight=""
            onBack={vi.fn()}
          />
        </SidePanel>,
      );
    });
    await act(async () => button('modals.chunk.edit')!.click());
    const field = document.body.querySelector('textarea')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => button('modals.chunk.save')!.click());
  };

  it('saving an untitled chunk sends no title', async () => {
    await saveEdit(
      { chunk_id: 'c1', text: 'Old', metadata: { source: 'a.md' } },
      'New',
    );
    expect(updateChunk).toHaveBeenCalledTimes(1);
    const body = updateChunk.mock.calls[0][0];
    expect(body).toEqual({ id: 'doc', chunk_id: 'c1', text: 'New' });
    expect(body.metadata?.title).toBeUndefined();
  });

  it('saving a titled chunk keeps its title', async () => {
    await saveEdit(
      { chunk_id: 'c1', text: 'Old', metadata: { title: 'Brief.md' } },
      'New',
    );
    expect(updateChunk).toHaveBeenCalledWith(
      {
        id: 'doc',
        chunk_id: 'c1',
        text: 'New',
        metadata: { title: 'Brief.md' },
      },
      'tok',
    );
  });

  it('the edit drawer edits the title like Chunks', async () => {
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <GraphChunkReader
            docId="doc"
            chunk={{ chunk_id: 'c1', text: 'Body', metadata: { title: 'Old' } }}
            highlight=""
            onBack={vi.fn()}
          />
        </SidePanel>,
      );
    });
    await act(async () => button('modals.chunk.edit')!.click());
    const input = document.body.querySelector(
      'input[type="text"], input:not([type])',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.value).toBe('Old');
    expect(document.body.textContent).toContain('modals.chunk.title');
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, ' New title ');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    // A title-only edit is a change: Save is enabled and sends it trimmed.
    await act(async () => button('modals.chunk.save')!.click());
    expect(updateChunk).toHaveBeenCalledWith(
      {
        id: 'doc',
        chunk_id: 'c1',
        text: 'Body',
        metadata: { title: 'New title' },
      },
      'tok',
    );
  });

  it('Open in Files opens the tree path, not a web page URL', async () => {
    const onOpenInFiles = vi.fn();
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <GraphChunkReader
            docId="doc"
            chunk={{
              chunk_id: 'c1',
              text: 'Body',
              metadata: {
                source: 'https://docs.example.com/guides/setup',
                file_path: 'guides/setup.md',
                title: 'Setup',
              },
            }}
            highlight=""
            onBack={vi.fn()}
            onOpenInFiles={onOpenInFiles}
          />
        </SidePanel>,
      );
    });
    await act(async () =>
      button('settings.sources.graphrag.view.openInFiles')!.click(),
    );
    expect(onOpenInFiles).toHaveBeenCalledWith('guides/setup.md');
  });

  // Leaving the edit drawer (Cancel, Discard, Esc, X) returns to the reader
  // on the same chunk; only a successful save goes back to the node.
  it('Cancel in the edit drawer returns to the reader', async () => {
    const onBack = vi.fn();
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <GraphChunkReader
            docId="doc"
            chunk={{ chunk_id: 'c1', text: 'Old body', metadata: {} }}
            highlight=""
            onBack={onBack}
          />
        </SidePanel>,
      );
    });
    await act(async () => button('modals.chunk.edit')!.click());
    expect(document.body.querySelector('textarea')).not.toBeNull();
    await act(async () => button('settings.sources.editor.cancel')!.click());
    expect(onBack).not.toHaveBeenCalled();
    expect(document.body.querySelector('textarea')).toBeNull();
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    expect(button('modals.chunk.edit')).toBeDefined();
    expect(document.body.textContent).toContain('Old body');
  });

  it('a successful save goes back to the node', async () => {
    const onBack = vi.fn();
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <GraphChunkReader
            docId="doc"
            chunk={{ chunk_id: 'c1', text: 'Old', metadata: {} }}
            highlight=""
            onBack={onBack}
          />
        </SidePanel>,
      );
    });
    await act(async () => button('modals.chunk.edit')!.click());
    const field = document.body.querySelector('textarea')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!.call(field, 'New');
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => button('modals.chunk.save')!.click());
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('heads the reader with a Back arrow, in the docked panel', async () => {
    const onBack = vi.fn();
    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <GraphChunkReader
            docId="doc"
            chunk={{ chunk_id: 'c1', text: '# Brief\n\nBody', metadata: {} }}
            highlight=""
            onBack={onBack}
          />
        </SidePanel>,
      );
    });
    const header = document.body.querySelector('[data-slot="panel-header"]')!;
    expect(header.closest('aside')).not.toBeNull();
    expect(header.querySelector('h2')?.textContent).toBe('Brief');
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    await act(async () =>
      (
        document.body.querySelector(
          'button[aria-label="sidePanel.back"]',
        ) as HTMLButtonElement
      ).click(),
    );
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
