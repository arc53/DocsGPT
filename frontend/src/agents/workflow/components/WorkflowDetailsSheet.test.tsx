import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({ useDispatch: () => vi.fn() }));
const getTopicFolders = vi.hoisted(() => vi.fn());
vi.mock('../../../api/services/userService', () => ({
  default: { getTopicFolders },
}));

import { DEFAULT_ANALYTICS } from '../../analyticsConfig';
import type { AnalyticsConfig } from '../../types';
import WorkflowDetailsSheet from './WorkflowDetailsSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const details = {
  name: 'Helpdesk Triage',
  description: 'Routes internal requests',
  allowPromptOverride: false,
  contextWindowLimit: null,
  historyTokenLimit: null,
};

describe('WorkflowDetailsSheet', () => {
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

  const render = (
    props: {
      errors?: string[];
      saving?: boolean;
      analytics?: AnalyticsConfig;
      available?: boolean;
      contextWindowLimit?: number | null;
      historyTokenLimit?: number | null;
      policyEditable?: boolean;
    } = {},
  ) => {
    const handlers = { onOpenChange: vi.fn(), onSave: vi.fn() };
    act(() => {
      root.render(
        <WorkflowDetailsSheet
          open
          details={{
            ...details,
            analytics: props.analytics,
            contextWindowLimit: props.contextWindowLimit ?? null,
            historyTokenLimit: props.historyTokenLimit ?? null,
          }}
          modelWindow={{ tokens: 128_000, name: 'Model One' }}
          policyEditable={props.policyEditable}
          insights={{
            available: props.available ?? true,
            maxTopics: 15,
            maxOverlapping: 20,
            agentId: 'wf-agent',
            token: 'token',
          }}
          currentImage=""
          saving={props.saving ?? false}
          errors={props.errors ?? []}
          {...handlers}
        />,
      );
    });
    return handlers;
  };

  const button = (name: string) =>
    Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === name,
    ) as HTMLButtonElement;

  const nameInput = () =>
    document.querySelector('input[type="text"]') as HTMLInputElement;

  const type = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('opens with the workflow details filled in', () => {
    render();
    expect(document.body.textContent).toContain(
      'agents.workflow.builder.detailsTitle',
    );
    expect(nameInput().value).toBe('Helpdesk Triage');
    expect(document.querySelector('textarea')?.value).toBe(
      'Routes internal requests',
    );
    expect(document.querySelector('[role="switch"]')).not.toBeNull();
  });

  // S8: square form controls; the footer actions stay pill chrome.
  it('draws the name and description as square default-size fields', () => {
    render();
    expect(nameInput().getAttribute('data-shape')).toBe('default');
    const description = document.querySelector('textarea');
    expect(description?.getAttribute('data-size')).toBe('default');
    expect(description?.className).toContain('h-32');
    expect(button('agents.form.buttons.save').getAttribute('data-shape')).toBe(
      'pill',
    );
  });

  it('keeps Save disabled until something changes, then saves the edits', () => {
    const { onSave } = render();
    const save = button('agents.form.buttons.save');
    expect(save.disabled).toBe(true);

    type(nameInput(), 'Helpdesk Router');
    expect(save.disabled).toBe(false);

    act(() => save.click());
    expect(onSave).toHaveBeenCalledWith({
      name: 'Helpdesk Router',
      description: 'Routes internal requests',
      allowPromptOverride: false,
      analytics: DEFAULT_ANALYTICS,
      contextWindowLimit: null,
      historyTokenLimit: null,
      imageFile: null,
    });
  });

  const limitInput = (key: 'contextLimitTokens' | 'historyLimitTokens') =>
    document.querySelector(
      `input[aria-label="agents.form.advanced.${key}"]`,
    ) as HTMLInputElement;
  const limitSwitch = (key: 'contextLimit' | 'historyLimit') => {
    const label = Array.from(document.querySelectorAll('label')).find(
      (el) => el.textContent === `agents.form.advanced.${key}`,
    )!;
    return document.getElementById(label.htmlFor) as HTMLButtonElement;
  };

  it('saves a context limit, and one switched off as null', () => {
    const { onSave } = render({ contextWindowLimit: 64000 });
    expect(limitInput('contextLimitTokens').value).toBe('64000');
    type(limitInput('contextLimitTokens'), '32000');
    act(() => button('agents.form.buttons.save').click());
    expect(onSave.mock.calls[0][0].contextWindowLimit).toBe(32000);

    act(() => limitSwitch('contextLimit').click());
    expect(limitInput('contextLimitTokens').disabled).toBe(true);
    act(() => button('agents.form.buttons.save').click());
    expect(onSave.mock.calls[1][0].contextWindowLimit).toBeNull();
  });

  it("notes, but saves, a context limit past the model's window", () => {
    const { onSave } = render({ contextWindowLimit: 64000 });
    type(limitInput('contextLimitTokens'), '200000');
    expect(limitInput('contextLimitTokens').getAttribute('aria-invalid')).toBe(
      null,
    );
    expect(document.body.textContent).toContain(
      'agents.form.advanced.contextLimitAboveWindow',
    );
    act(() => button('agents.form.buttons.save').click());
    expect(onSave.mock.calls[0][0].contextWindowLimit).toBe(200000);
  });

  it('keeps Save disabled while a limit is out of range', () => {
    render({ contextWindowLimit: 64000 });
    type(limitInput('contextLimitTokens'), '12000');
    expect(button('agents.form.buttons.save').disabled).toBe(true);
    expect(limitInput('contextLimitTokens').getAttribute('aria-invalid')).toBe(
      'true',
    );
    expect(document.body.textContent).toContain(
      'agents.form.advanced.limitRange',
    );
  });

  it('saves a history limit, noting one at the window', () => {
    const { onSave } = render();
    act(() => limitSwitch('historyLimit').click());
    expect(limitInput('historyLimitTokens').value).toBe('8000');
    type(limitInput('historyLimitTokens'), '128000');
    expect(button('agents.form.buttons.save').disabled).toBe(false);
    expect(document.body.textContent).toContain(
      'agents.form.advanced.historyLimitAboveWindow',
    );
    type(limitInput('historyLimitTokens'), '3000');
    expect(button('agents.form.buttons.save').disabled).toBe(true);
    expect(document.body.textContent).toContain(
      'agents.form.advanced.limitRange',
    );
    type(limitInput('historyLimitTokens'), '12000');
    act(() => button('agents.form.buttons.save').click());
    expect(onSave.mock.calls[0][0].historyTokenLimit).toBe(12000);
  });

  it("saves an unrelated edit with a stored limit past the model's window", () => {
    const { onSave } = render({
      policyEditable: false,
      contextWindowLimit: 200_000,
    });
    type(nameInput(), 'Helpdesk Router');
    act(() => button('agents.form.buttons.save').click());
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0].contextWindowLimit).toBe(200_000);
  });

  it('shows the limits read-only without edit_policy', () => {
    render({ policyEditable: false, contextWindowLimit: 64000 });
    expect(limitInput('contextLimitTokens').disabled).toBe(true);
    expect(limitSwitch('contextLimit').disabled).toBe(true);
    expect(limitSwitch('historyLimit').disabled).toBe(true);
  });

  it('closes on Cancel without saving', () => {
    const { onOpenChange, onSave } = render();
    type(nameInput(), 'Something else');
    act(() => button('agents.form.buttons.cancel').click());
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('lists save errors in an alert inside the sheet', () => {
    render({ errors: ['Workflow must have an end node'] });
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('agents.workflow.builder.unableSave');
    expect(alert?.textContent).toContain('Workflow must have an end node');
  });

  it('sits in a side panel: fixed header with the X, one scroller, a footer', () => {
    const { onOpenChange } = render();
    const header = document.querySelector('[data-slot="panel-header"]')!;
    expect(header.querySelector('[data-slot="sheet-title"]')?.textContent).toBe(
      'agents.workflow.builder.detailsTitle',
    );
    expect(
      header.querySelector('[data-slot="sheet-description"]')?.textContent,
    ).toBe('agents.workflow.builder.detailsDescription');
    expect(document.querySelectorAll('.overflow-y-auto')).toHaveLength(1);
    expect(document.querySelector('.pr-12')).toBeNull();
    act(() =>
      header
        .querySelector<HTMLButtonElement>('[aria-label="sidePanel.close"]')!
        .click(),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  const insightsCard = () =>
    Array.from(document.querySelectorAll('[data-slot="card"]')).find(
      (card) =>
        card.querySelector('h3')?.textContent ===
        'agents.form.sections.analytics',
    );

  // IN-21: a workflow's insights, in a third card after Basics and Advanced.
  it('holds an Insights card after Advanced, its sub-headings one level down', () => {
    render();
    const cards = Array.from(document.querySelectorAll('[data-slot="card"]'));
    const card = insightsCard()!;
    expect(cards.indexOf(card)).toBe(2);
    expect(
      card.querySelector('[data-testid="analytics-topics"] h4'),
    ).not.toBeNull();
    // A workflow has no sources of its own: its topics are its own list.
    expect(card.textContent).toContain('agents.form.analytics.empty.workflow');
    expect(getTopicFolders).not.toHaveBeenCalled();
  });

  it('counts an insights change as an edit and saves it with the rest', () => {
    const { onSave } = render();
    const save = button('agents.form.buttons.save');
    const digest = document.querySelector<HTMLButtonElement>(
      '[data-testid="analytics-digest"]',
    )!;
    act(() => digest.click());
    expect(save.disabled).toBe(false);
    act(() => digest.click());
    expect(save.disabled).toBe(true);
    act(() => digest.click());
    act(() => save.click());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        analytics: { ...DEFAULT_ANALYTICS, digest: true },
      }),
    );
  });

  it('hides the card while the server has insights off, unless the workflow has settings of its own', () => {
    render({ available: false });
    expect(insightsCard()).toBeUndefined();
    render({
      available: false,
      analytics: { ...DEFAULT_ANALYTICS, digest: true },
    });
    expect(insightsCard()!.textContent).toContain(
      'agents.form.analytics.serverOff',
    );
  });
});
