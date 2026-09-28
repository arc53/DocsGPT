import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { type Node } from 'reactflow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import NodePanel from './NodePanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const agentNode: Node = {
  id: 'classify',
  type: 'agent',
  position: { x: 0, y: 0 },
  data: { title: 'Classify request' },
};

const startNode: Node = {
  id: 'start',
  type: 'start',
  position: { x: 0, y: 0 },
  data: { label: 'Start' },
};

describe('NodePanel', () => {
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
    document.body.innerHTML = '';
  });

  const render = (node: Node) => {
    const handlers = {
      onClose: vi.fn(),
      onDuplicate: vi.fn(),
      onDelete: vi.fn(),
      onUpdate: vi.fn(),
    };
    act(() => {
      root.render(
        <NodePanel node={node} {...handlers}>
          <div data-testid="body">body</div>
        </NodePanel>,
      );
    });
    return handlers;
  };

  const menuTrigger = () =>
    container.querySelector(
      '[aria-label="agents.workflow.builder.nodeActions"]',
    ) as HTMLButtonElement | null;

  it('shows the icon, own title, type badge and id', () => {
    render(agentNode);
    const header = container.querySelector('header')!;
    expect(header.textContent).toContain('Classify request');
    const badge = header.querySelector('[data-slot="badge"]')!;
    expect(badge.textContent).toBe('agents.workflow.builder.aiAgent');
    expect(badge.getAttribute('data-variant')).toBe('neutral');
    expect(header.textContent).toContain('classify');
    expect(header.querySelector('.bg-secondary')).not.toBeNull();
  });

  it('offers Duplicate and Delete node in the node menu', () => {
    const { onDuplicate, onDelete } = render(agentNode);
    const trigger = menuTrigger();
    expect(trigger).not.toBeNull();
    act(() => {
      trigger!.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const items = Array.from(
      document.querySelectorAll('[role="menuitem"]'),
    ) as HTMLElement[];
    expect(items.map((i) => i.textContent)).toEqual([
      'agents.workflow.builder.duplicateNode',
      'agents.workflow.builder.deleteNode',
    ]);
    expect(items[1].getAttribute('data-variant')).toBe('destructive');
    act(() => items[0].click());
    expect(onDuplicate).toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('has no node menu and no title field for the start node', () => {
    render(startNode);
    expect(menuTrigger()).toBeNull();
    expect(container.querySelector('input')).toBeNull();
    expect(container.textContent).not.toContain('cannotDeleteStart');
  });

  it('closes from the header', () => {
    const { onClose } = render(agentNode);
    const close = container.querySelector(
      '[aria-label="agents.close"]',
    ) as HTMLButtonElement;
    act(() => close.click());
    expect(onClose).toHaveBeenCalled();
  });

  it('edits the title on the background surface and renders the body', () => {
    const { onUpdate } = render(agentNode);
    const label = container.querySelector(
      '[data-slot="form-field-label"]',
    ) as HTMLElement;
    expect(label.className).toContain('bg-background');
    expect(container.querySelector('[data-testid="body"]')).not.toBeNull();
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
