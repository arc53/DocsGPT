import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../api/services/teamsService', () => ({
  default: { searchAdminTeams: vi.fn() },
}));

import teamsService from '../api/services/teamsService';
import TeamPicker from './TeamPicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TeamPicker', () => {
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

  it('is a field-height combobox', () => {
    act(() => {
      root.render(
        <TeamPicker value={null} onChange={() => undefined} token="tok" />,
      );
    });
    const trigger = container.querySelector('[role="combobox"]');
    expect(trigger?.getAttribute('data-size')).toBe('field');
  });

  it('is the shared Combobox: one rotating ChevronDown, modal, 18rem min', async () => {
    vi.mocked(teamsService.searchAdminTeams).mockResolvedValue({
      teams: [
        { id: 't1', name: 'Customer Support' },
        { id: 't2', name: 'People Ops' },
      ],
    });
    act(() => {
      root.render(
        <TeamPicker
          value={{ id: 't2', name: 'People Ops' }}
          onChange={() => undefined}
          token="tok"
        />,
      );
    });
    const trigger =
      container.querySelector<HTMLButtonElement>('[role="combobox"]')!;
    expect(trigger.dataset.slot).toBe('combobox-trigger');
    expect(trigger.getAttribute('aria-label')).toBe('Team');
    expect(trigger.className.split(' ')).toContain('w-52');
    expect(trigger.querySelector('.lucide-chevron-down')).not.toBeNull();
    expect(trigger.querySelector('.lucide-chevrons-up-down')).toBeNull();
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    await act(async () => undefined);
    const content = document.body.querySelector<HTMLElement>(
      '[data-slot="popover-content"]',
    )!;
    expect(content.className).toContain(
      'min-w-(--radix-popover-trigger-width)',
    );
    expect(content.dataset.align).toBe('end');
    const items = Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );
    expect(items.map((i) => i.textContent)).toEqual([
      'Customer Support',
      'People Ops',
    ]);
    expect(items[1].dataset.checked).toBe('true');
  });
});
