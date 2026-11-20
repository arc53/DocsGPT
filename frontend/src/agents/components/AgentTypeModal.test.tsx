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
    const buttons = () =>
      Array.from(document.body.querySelectorAll<HTMLButtonElement>('button'));
    const byText = (text: string) =>
      buttons().find((button) => button.textContent?.includes(text))!;
    const build = () => byText('drafter.build');
    const chips = () =>
      Array.from(
        document.body.querySelectorAll<HTMLButtonElement>(
          '[data-template-chip]',
        ),
      );
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

    it('leads with the describe box and the featured templates as chips', async () => {
      await render();
      expect(tiles()).toHaveLength(0);
      expect(document.body.textContent).toContain('agents.typeModal.newTitle');
      expect(document.body.textContent).toContain(
        'agents.typeModal.draftDescription',
      );
      expect(describeBox().getAttribute('aria-label')).toBe(
        'agents.typeModal.describeLabel',
      );
      expect(document.body.textContent).toContain(
        'agents.typeModal.templatesLabel',
      );
      expect(chips().map((chip) => chip.textContent)).toEqual([
        'drafter.starters.website.short',
        'drafter.starters.helpdesk.short',
        'drafter.starters.research.short',
      ]);
    });

    it('puts the blank starts and Build in the footer', async () => {
      await render();
      const footer = document.body.querySelector('[data-slot="modal-footer"]')!;
      const labels = Array.from(footer.querySelectorAll('button')).map(
        (button) => button.textContent,
      );
      expect(labels).toEqual([
        'agents.typeModal.blankAgent',
        'agents.typeModal.blankWorkflow',
        'drafter.build',
      ]);
    });

    it('keeps Build disabled until something is written', async () => {
      await render();
      expect(build().disabled).toBe(true);
      await type('   ');
      expect(build().disabled).toBe(true);
      await type('Answers shipping questions');
      expect(build().disabled).toBe(false);
    });

    it('opens the blank classic form with no draft start', async () => {
      const onClose = await render();
      await act(async () => byText('agents.typeModal.blankAgent').click());
      expect(navigate).toHaveBeenCalledTimes(1);
      expect(navigate.mock.calls[0]).toHaveLength(1);
      expect(String(navigate.mock.calls[0][0])).not.toContain('workflow');
      expect(onClose).toHaveBeenCalled();
    });

    it('opens the blank workflow builder', async () => {
      await render();
      await act(async () => byText('agents.typeModal.blankWorkflow').click());
      expect(String(navigate.mock.calls[0][0])).toContain('workflow');
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

    it('builds on Ctrl or Cmd+Enter, never with an empty field', async () => {
      await render();
      const press = async (init: KeyboardEventInit) =>
        act(async () => {
          describeBox().dispatchEvent(
            new KeyboardEvent('keydown', {
              key: 'Enter',
              bubbles: true,
              ...init,
            }),
          );
        });
      await press({ ctrlKey: true });
      expect(navigate).not.toHaveBeenCalled();
      await type('Answers shipping questions');
      await press({});
      expect(navigate).not.toHaveBeenCalled();
      await press({ metaKey: true });
      expect(navigate).toHaveBeenCalledTimes(1);
      expect(navigate.mock.calls[0][1].state.draftStart.text).toBe(
        'Answers shipping questions',
      );
    });

    it('hands a template over by its id', async () => {
      await render();
      await act(async () => chips()[1].click());
      expect(navigate.mock.calls[0][1]).toEqual({
        state: { draftStart: { starter: 'helpdesk' } },
      });
    });
  });
});
