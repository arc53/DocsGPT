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
import GraphChunkSheet from './GraphChunkSheet';

const updateChunk = (
  userService as unknown as { updateChunk: ReturnType<typeof vi.fn> }
).updateChunk;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('GraphChunkSheet', () => {
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
        <GraphChunkSheet
          docId="doc"
          chunk={chunk}
          highlight=""
          onClose={vi.fn()}
        />,
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
        <GraphChunkSheet
          docId="doc"
          chunk={{ chunk_id: 'c1', text: 'Body', metadata: { title: 'Old' } }}
          highlight=""
          onClose={vi.fn()}
        />,
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
        <GraphChunkSheet
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
          onClose={vi.fn()}
          onOpenInFiles={onOpenInFiles}
        />,
      );
    });
    await act(async () =>
      button('settings.sources.graphrag.view.openInFiles')!.click(),
    );
    expect(onOpenInFiles).toHaveBeenCalledWith('guides/setup.md');
  });

  // Leaving the edit drawer (Cancel, Discard, Esc, X) returns to the read
  // drawer on the same chunk; only a successful save closes both.
  it('Cancel in the edit drawer returns to the read drawer', async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <GraphChunkSheet
          docId="doc"
          chunk={{ chunk_id: 'c1', text: 'Old body', metadata: {} }}
          highlight=""
          onClose={onClose}
        />,
      );
    });
    await act(async () => button('modals.chunk.edit')!.click());
    expect(document.body.querySelector('textarea')).not.toBeNull();
    await act(async () => button('settings.sources.editor.cancel')!.click());
    expect(onClose).not.toHaveBeenCalled();
    expect(document.body.querySelector('textarea')).toBeNull();
    expect(button('modals.chunk.edit')).toBeDefined();
    expect(document.body.textContent).toContain('Old body');
  });

  it('a successful save closes both drawers', async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <GraphChunkSheet
          docId="doc"
          chunk={{ chunk_id: 'c1', text: 'Old', metadata: {} }}
          highlight=""
          onClose={onClose}
        />,
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
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
