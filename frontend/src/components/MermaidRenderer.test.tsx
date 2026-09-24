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

    // The diagram host is the only <pre> while the code view is closed.
    expect(container.querySelectorAll('pre')).toHaveLength(1);
    expect(container.querySelector('pre')?.id).toMatch(/^mermaid-/);
    expect(container.querySelector('svg[data-rendered="true"]')).not.toBeNull();
  });

  it('opens the Download menu with a menu item per format', async () => {
    renderMermaidDiagramMock.mockResolvedValue({ svg: '<svg></svg>' });

    await act(async () => {
      root.render(
        <MermaidRenderer code={'flowchart LR\nA --> B'} isLoading={false} />,
      );
    });

    const trigger = container.querySelector<HTMLButtonElement>(
      'button[title="mermaid.downloadOptions"]',
    );
    expect(trigger).not.toBeNull();
    expect(trigger?.getAttribute('aria-haspopup')).toBe('menu');
    expect(document.querySelector('[role="menu"]')).toBeNull();

    await act(async () => {
      trigger?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });

    expect(trigger?.getAttribute('aria-expanded')).toBe('true');
    const items = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).map((item) => item.textContent);
    expect(items).toEqual([
      'Download as SVG',
      'Download as PNG',
      'Download as MMD',
    ]);
  });
});
