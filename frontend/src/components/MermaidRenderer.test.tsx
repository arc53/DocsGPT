import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const renderMermaidDiagramMock = vi.hoisted(() => vi.fn());

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useSelector: () => 'idle' }));
vi.mock('../hooks', () => ({ useDarkTheme: () => [false] }));
vi.mock('./CopyButton', () => ({ default: () => null }));
vi.mock('./mermaidSecurity', () => ({
  renderMermaidDiagram: renderMermaidDiagramMock,
}));

import MermaidRenderer from './MermaidRenderer';

describe('MermaidRenderer', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    renderMermaidDiagramMock.mockReset();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('keeps its visible host when Mermaid removes its temporary render ID', async () => {
    renderMermaidDiagramMock.mockImplementation(
      async ({ id }: { id: string }) => {
        // Mermaid removes an existing node with the supplied render ID.
        document.getElementById(id)?.remove();
        return { svg: '<svg data-rendered="true"></svg>' };
      },
    );

    await act(async () => {
      root.render(
        <MermaidRenderer code={'flowchart LR\nA --> B'} isLoading={false} />,
      );
    });

    expect(container.querySelector('pre.mermaid')).not.toBeNull();
    expect(container.querySelector('svg[data-rendered="true"]')).not.toBeNull();
  });
});
