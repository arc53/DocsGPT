import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import TraceSpanDetails from './TraceSpanDetails';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TraceSpanDetails', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const span = {
    id: 's1',
    parent_id: null,
    kind: 'tool',
    name: 'search',
    status: 'error',
    offset_ms: 0,
    duration_ms: 12,
    attributes: { 'docsgpt.tool': 'search' },
    error: 'TimeoutError',
    preview: {
      arguments: { query: 'iso' },
      query: 'Nordhaven ISO',
      chunks: [{ title: 'Cert', score: 0.9, text: 'valid' }],
    },
  };

  it('shows previews in ui/code-block panels with the shared scroll caps', () => {
    act(() => root.render(<TraceSpanDetails span={span} />));
    const blocks = Array.from(
      container.querySelectorAll<HTMLElement>('pre[data-slot="code-block"]'),
    );
    // Error, query, arguments and all attributes are CodeBlocks.
    expect(blocks.map((b) => b.textContent)).toEqual(
      expect.arrayContaining(['TimeoutError', 'Nordhaven ISO']),
    );
    const query = blocks.find((b) => b.textContent === 'Nordhaven ISO')!;
    expect(query.className).toContain('font-sans');
    expect(query.parentElement!.className).toContain('max-h-60');
    const args = blocks.find((b) => b.textContent?.includes('"query"'))!;
    expect(args.className).toContain('font-mono');
    expect(args.closest('.bg-answer-surface')).not.toBeNull();
    // The chunk list takes the lg cap (320px).
    const chunkList = container.querySelector('ol')!;
    expect(chunkList.parentElement!.className).toContain('max-h-80');
    // No hand-made caps left over.
    expect(container.innerHTML).not.toContain('max-h-72');
  });
});
