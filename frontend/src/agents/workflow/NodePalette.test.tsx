import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import NodePalette from './NodePalette';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('NodePalette', () => {
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

  const render = (onAdd = vi.fn(), onDragStart = vi.fn()) => {
    act(() => {
      root.render(<NodePalette onAdd={onAdd} onDragStart={onDragStart} />);
    });
    return { onAdd, onDragStart };
  };

  const pill = (labelKey: string) =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(labelKey),
    ) as HTMLButtonElement;

  it('renders each node type as a draggable button', () => {
    render();
    const buttons = container.querySelectorAll('button');
    expect(buttons).toHaveLength(6);
    buttons.forEach((button) => {
      expect(button.getAttribute('type')).toBe('button');
      expect(button.getAttribute('draggable')).toBe('true');
    });
  });

  it('adds a node of the pill type on click', () => {
    const { onAdd } = render();
    act(() => pill('agents.workflow.nodes.condition').click());
    expect(onAdd).toHaveBeenCalledWith('condition');
    act(() => pill('agents.workflow.builder.aiAgent').click());
    expect(onAdd).toHaveBeenLastCalledWith('agent');
  });

  it('starts a drag with the pill type', () => {
    const { onDragStart } = render();
    const button = pill('agents.workflow.nodes.code');
    act(() => {
      button.dispatchEvent(new Event('dragstart', { bubbles: true }));
    });
    expect(onDragStart).toHaveBeenCalledWith(expect.anything(), 'code');
  });

  it('shows the shared tone on the icon square, with no hover swap', () => {
    render();
    const square = pill('agents.workflow.nodes.end').querySelector(
      'span',
    ) as HTMLElement;
    expect(square.className).toContain('bg-success/10');
    // Radius by role: a tinted icon square at size-8 is rounded-md.
    expect(square.className).toContain('rounded-md');
    expect(container.innerHTML).not.toContain('group-hover:');
  });

  it('explains click-to-add under the groups', () => {
    render();
    expect(container.textContent).toContain(
      'agents.workflow.builder.paletteHint',
    );
  });
});
