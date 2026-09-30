import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../api/services/teamsService', () => ({
  default: { searchAdminTeams: vi.fn() },
}));

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
});
