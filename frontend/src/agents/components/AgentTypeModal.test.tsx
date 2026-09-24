import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
}));

import AgentTypeModal from './AgentTypeModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentTypeModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    navigate.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (onClose = vi.fn()) => {
    await act(async () => {
      root.render(<AgentTypeModal isOpen onClose={onClose} folderId="f1" />);
    });
    return onClose;
  };

  const tiles = () =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="option-card"]',
      ),
    );

  it('renders the two agent types as OptionCards', async () => {
    await render();
    const found = tiles();
    expect(found).toHaveLength(2);
    expect(found[0].textContent).toContain('Classic Agent');
    expect(found[1].textContent).toContain('Workflow Agent');
    expect(found[0].querySelector('[data-slot="option-card-icon"]')).not.toBe(
      null,
    );
    expect(found[0].querySelector('[data-slot="card-description"]')).not.toBe(
      null,
    );
  });

  it('navigates to the workflow builder and closes', async () => {
    const onClose = await render();
    await act(async () => tiles()[1].click());
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(String(navigate.mock.calls[0][0])).toContain('workflow');
    expect(onClose).toHaveBeenCalled();
  });

  it('navigates to the classic form and closes', async () => {
    const onClose = await render();
    await act(async () => tiles()[0].click());
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(String(navigate.mock.calls[0][0])).not.toContain('workflow');
    expect(onClose).toHaveBeenCalled();
  });
});
