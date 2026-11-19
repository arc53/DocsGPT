import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
}));

const drafter = vi.hoisted(() => ({
  config: null as { enabled: boolean } | null,
  wanted: [] as boolean[],
}));
vi.mock('react-redux', () => ({ useSelector: () => 'token' }));
vi.mock('../../drafter/useDrafterConfig', () => ({
  useDrafterConfigFor: (_token: string | null, wanted = true) => {
    drafter.wanted.push(wanted);
    return wanted ? drafter.config : null;
  },
}));

import { TooltipProvider } from '../../components/ui/tooltip';
import AgentTypeModal from './AgentTypeModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentTypeModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    navigate.mockReset();
    drafter.config = null;
    drafter.wanted = [];
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
      root.render(
        <TooltipProvider>
          <AgentTypeModal isOpen onClose={onClose} folderId="f1" />
        </TooltipProvider>,
      );
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
    expect(found[0].textContent).toContain('agents.typeModal.classicTitle');
    expect(found[1].textContent).toContain('agents.typeModal.workflowTitle');
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

  it('reads nothing about the drafter while closed', async () => {
    drafter.config = { enabled: true };
    await act(async () => {
      root.render(
        <TooltipProvider>
          <AgentTypeModal isOpen={false} onClose={vi.fn()} />
        </TooltipProvider>,
      );
    });
    expect(tiles()).toHaveLength(0);
    expect(drafter.wanted.length).toBeGreaterThan(0);
    expect(drafter.wanted).not.toContain(true);
  });

  it('shows only the blank starts while the drafter is off', async () => {
    drafter.config = { enabled: false };
    await render();
    expect(tiles()).toHaveLength(2);
    expect(document.body.querySelector('textarea')).toBeNull();
    expect(document.body.querySelector('[data-drafter-entry]')).toBeNull();
    expect(document.body.textContent).toContain('agents.typeModal.description');
  });

  describe('with the drafter on', () => {
    beforeEach(() => {
      drafter.config = { enabled: true };
    });

    const describeBox = () =>
      document.body.querySelector<HTMLTextAreaElement>('textarea')!;
    const build = () =>
      document.body.querySelector<HTMLButtonElement>('[data-drafter-entry]')!;
    const type = async (value: string) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!;
      await act(async () => {
        setter.call(describeBox(), value);
        describeBox().dispatchEvent(new Event('input', { bubbles: true }));
      });
    };

    it('puts the blank starts first, then the describe box and the starting points', async () => {
      await render();
      const found = tiles();
      expect(found.map((tile) => tile.textContent)).toEqual([
        expect.stringContaining('agents.typeModal.classicTitle'),
        expect.stringContaining('agents.typeModal.workflowTitle'),
        expect.stringContaining('drafter.starters.website.title'),
        expect.stringContaining('drafter.starters.helpdesk.title'),
        expect.stringContaining('drafter.starters.research.title'),
      ]);
      expect(
        found[1].compareDocumentPosition(describeBox()) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(build().textContent).toContain('drafter.build');
      expect(document.body.textContent).toContain(
        'agents.typeModal.draftDescription',
      );
    });

    it('still opens the blank classic form with no draft start', async () => {
      await render();
      await act(async () => tiles()[0].click());
      expect(navigate).toHaveBeenCalledTimes(1);
      expect(navigate.mock.calls[0]).toHaveLength(1);
    });

    it('hands the description to the new-agent form and closes', async () => {
      const onClose = await render();
      await type('  Answers shipping questions  ');
      await act(async () => build().click());
      expect(navigate).toHaveBeenCalledTimes(1);
      const [path, options] = navigate.mock.calls[0];
      expect(String(path)).toContain('folder_id=f1');
      expect(String(path)).not.toContain('workflow');
      expect(options.state.draftStart.text.trim()).toBe(
        'Answers shipping questions',
      );
      expect(onClose).toHaveBeenCalled();
    });

    it('opens the drawer alone when Build is pressed with nothing written', async () => {
      await render();
      await act(async () => build().click());
      expect(navigate.mock.calls[0][1]).toEqual({ state: { draftStart: {} } });
    });

    it('hands a starting point over by its id', async () => {
      await render();
      await act(async () => tiles()[3].click());
      expect(navigate.mock.calls[0][1]).toEqual({
        state: { draftStart: { starter: 'helpdesk' } },
      });
    });
  });
});
