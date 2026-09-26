import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { GuardrailCatalog, GuardrailsConfig } from '../types';

const getGuardrailCatalog = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getGuardrailCatalog: (...args: unknown[]) => getGuardrailCatalog(...args),
  },
}));

// A stable `t`: the component refetches the catalog whenever `t` changes.
const t = (key: string) => key;
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t }),
}));

import GuardrailsSection from './GuardrailsSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const catalog: GuardrailCatalog = {
  enabled: false,
  checks: [
    {
      name: 'pii',
      label: 'PII',
      description: 'Detects personal data',
      stages: ['input', 'output'],
      supports_redaction: true,
      latency_hint_ms: 50,
      remote: false,
      available: false,
    },
    {
      name: 'policy',
      label: 'Policy',
      description: 'LLM judge',
      stages: ['input'],
      supports_redaction: false,
      latency_hint_ms: 1500,
      remote: true,
      available: true,
    },
  ],
  stages: ['input', 'output'],
  modes: ['monitor_only', 'scan_all'],
  actions_by_stage: {
    input: ['flag', 'block'],
    retrieval: ['flag'],
    tool_result: ['flag'],
    output: ['flag', 'redact', 'block'],
  },
  default_block_message: 'No',
  pii_entities: ['EMAIL', 'PHONE'],
  default_pii_entities: ['EMAIL'],
  floor: {
    enabled: true,
    mode: 'scan_all',
    fail_open: true,
    timeout_ms: 2000,
    block_message: '',
    controls: [
      {
        check: 'pii',
        stage: 'output',
        action: 'block',
        enabled: true,
        settings: {},
      },
    ],
  },
};

const config: GuardrailsConfig = {
  enabled: true,
  mode: 'monitor_only',
  fail_open: true,
  timeout_ms: 2000,
  block_message: 'Sorry',
  controls: [
    {
      check: 'pii',
      stage: 'input',
      action: 'flag',
      enabled: true,
      settings: { entities: ['EMAIL'] },
    },
    {
      check: 'policy',
      stage: 'input',
      action: 'flag',
      enabled: true,
      settings: { policy: '' },
    },
    {
      check: 'gone',
      stage: 'input',
      action: 'flag',
      enabled: true,
      settings: {},
    },
  ],
};

describe('GuardrailsSection', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getGuardrailCatalog.mockReset();
    getGuardrailCatalog.mockResolvedValue({
      json: async () => ({ success: true, ...catalog }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const q = (testId: string) =>
    container.querySelector<HTMLElement>(`[data-testid="${testId}"]`);

  const render = async (
    props: Partial<Parameters<typeof GuardrailsSection>[0]> = {},
  ) => {
    await act(async () => {
      root.render(
        <GuardrailsSection
          value={config}
          onChange={() => undefined}
          token="tok"
          disabledNotice="Read only"
          {...props}
        />,
      );
    });
    await act(async () => {
      q('guardrails-toggle')?.click();
    });
  };

  it('announces whether the section is open with aria-expanded', async () => {
    await render();
    expect(q('guardrails-toggle')?.getAttribute('aria-expanded')).toBe('true');
    await act(async () => {
      q('guardrails-toggle')?.click();
    });
    expect(q('guardrails-toggle')?.getAttribute('aria-expanded')).toBe('false');
  });

  // Decision 64: the header is a section-toggle with a leading lucide
  // chevron; the badges sit beside it and the panel draws the focus ring.
  it('renders the header as a section-toggle with the badges beside it', async () => {
    await render();
    const toggle = q('guardrails-toggle')!;
    expect(toggle.dataset.variant).toBe('section-toggle');
    expect(toggle.dataset.size).toBe('sm');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const chevron = toggle.firstElementChild!;
    expect(chevron.matches('svg.lucide-chevron-right')).toBe(true);
    expect(chevron.getAttribute('class')).toContain('rotate-90');
    expect(toggle.querySelectorAll('svg')).toHaveLength(1);
    // The heading wraps the button (a button's children are presentational,
    // so a heading inside it would be lost to screen readers).
    expect(toggle.querySelector('h2')).toBeNull();
    const heading = toggle.closest('h2')!;
    expect(heading.textContent).toBe('agents.form.sections.guardrails');

    const active = q('guardrails-active-badge')!;
    const incomplete = q('guardrails-incomplete-badge')!;
    expect(toggle.contains(active)).toBe(false);
    expect(toggle.contains(incomplete)).toBe(false);
    expect(active.parentElement).toBe(heading.parentElement);
    expect(heading.parentElement?.firstElementChild).toBe(heading);

    const panel = q('guardrails-section')!;
    expect(panel.contains(toggle)).toBe(true);
    expect(panel.className).toContain(
      'has-[[data-variant=section-toggle]:focus-visible]:ring-3',
    );
    expect(panel.className).toContain('bg-card');

    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(chevron.getAttribute('class')).not.toContain('rotate-90');
  });

  it('renders the header pills as badges in their status roles', async () => {
    await render();
    expect(q('guardrails-active-badge')?.dataset.slot).toBe('badge');
    expect(q('guardrails-active-badge')?.dataset.variant).toBe('success');
    expect(q('guardrails-incomplete-badge')?.dataset.variant).toBe(
      'destructive',
    );
    expect(q('guardrail-latency-pii')?.dataset.variant).toBe('neutral');
    expect(q('guardrail-latency-pii')?.title).toBe(
      'agents.form.guardrails.latencyHint',
    );
  });

  it('shows the section notices as polite or warning alerts', async () => {
    await render({ disabled: true });
    const readOnly = q('guardrails-read-only');
    expect(readOnly?.getAttribute('role')).toBe('status');
    expect(readOnly?.textContent).toContain('Read only');
    const instance = q('guardrails-instance-disabled');
    expect(instance?.getAttribute('role')).toBe('alert');
    expect(instance?.className).toContain('text-warning');
    const floor = Array.from(
      container.querySelectorAll<HTMLElement>('[role]'),
    ).find((el) =>
      el.textContent?.includes('agents.form.guardrails.floorNotice'),
    );
    expect(floor?.getAttribute('role')).toBe('status');
    expect(floor?.className).toContain('text-info');
  });

  // Item 38: the instance-policy line is an info Alert announced as a note.
  it('renders an instance-enforced control as an info note', async () => {
    await render();
    const note = q('guardrail-floor-pii:output')!;
    expect(note.dataset.slot).toBe('alert');
    expect(note.getAttribute('role')).toBe('note');
    expect(note.className).toContain('text-info');
    expect(note.querySelector('svg.lucide-info')).not.toBeNull();
    expect(note.textContent).toContain('agents.form.guardrails.floorControl');
  });

  // Item 38: a control's setup error is its FormField error, tied to the
  // action select.
  it('announces the setup error under the control row', async () => {
    await render();
    const error = q('guardrail-needs-setup-policy-input')!;
    expect(error.getAttribute('role')).toBe('alert');
    expect(error.textContent).toBe('agents.form.guardrails.setupRequired');
    expect(q('guardrail-needs-setup-pii-input')).toBeNull();
  });

  it('announces an empty PII entity list', async () => {
    await render({
      value: {
        ...config,
        controls: [{ ...config.controls[0], settings: { entities: [] } }],
      },
    });
    await act(async () => {
      q('guardrail-configure-pii-input')?.click();
    });
    const errors = Array.from(container.querySelectorAll('[role="alert"]')).map(
      (el) => el.textContent,
    );
    expect(errors).toContain('agents.form.guardrails.pickAtLeastOne');
  });

  it('uses the pressed-toggle variants for stage chips', async () => {
    await render();
    expect(q('guardrail-stage-pii-input')?.dataset.variant).toBe('secondary');
    const locked = q('guardrail-stage-pii-output');
    expect(locked?.dataset.variant).toBe('secondary');
    expect((locked as HTMLButtonElement).disabled).toBe(true);
    // The hint lives on the hoverable wrapper; the named button has no title.
    expect(locked?.hasAttribute('title')).toBe(false);
    expect(locked?.parentElement?.title).toBe(
      'agents.form.guardrails.lockedByFloor',
    );
    expect(q('guardrail-stage-policy-input')?.dataset.variant).toBe(
      'secondary',
    );
  });

  it('renders remove actions as ghost-destructive xs buttons', async () => {
    await render();
    const remove = q('guardrail-remove-pii-input');
    expect(remove?.dataset.variant).toBe('ghost-destructive');
    expect(remove?.dataset.size).toBe('xs');
    const orphan = q('guardrail-orphan-gone')?.querySelector('button');
    // On the tinted orphan row the hover is a destructive tint, not grey.
    expect(orphan?.dataset.variant).toBe('ghost-destructive-on-accent');
    expect(orphan?.dataset.size).toBe('xs');
  });

  it('draws the orphan-guardrail row as a small destructive Card', async () => {
    await render();
    const row = q('guardrail-orphan-gone');
    expect(row?.dataset.slot).toBe('card');
    expect(row?.dataset.tone).toBe('destructive');
    expect(row?.dataset.padding).toBe('sm');
  });

  // Decision 63 (3): the form's fields and selects are all 42px.
  it('sizes the fields through Input and Textarea props', async () => {
    await render();
    const block = q('guardrails-block-message');
    expect(block?.dataset.size).toBe('default');
    expect(block?.dataset.shape).toBe('pill');
    expect(block?.className).not.toContain('bg-card');
    const timeout = q('guardrails-timeout');
    expect(timeout?.dataset.variant).toBe('filled');
    expect(timeout?.dataset.size).toBe('default');
    expect(timeout?.dataset.shape).toBe('pill');
    const mode = q('guardrails-mode');
    expect(mode?.dataset.size).toBe('field');
    expect(mode?.dataset.shape).toBe('pill');

    await act(async () => {
      q('guardrail-configure-policy-input')?.click();
    });
    expect(q('guardrail-policy-text')?.dataset.slot).toBe('textarea');
  });

  // Decision 63e-b: the monitor-only line is advice, so the field's muted hint.
  it('explains monitor-only mode in the mode field hint', async () => {
    await render();
    const hint = Array.from(container.querySelectorAll('p')).find(
      (p) => p.textContent === 'agents.form.guardrails.monitorHint',
    )!;
    expect(hint.className.split(' ')).toEqual(
      expect.arrayContaining(['text-muted-foreground', 'text-xs']),
    );
    expect(hint.className).not.toContain('text-warning');
    expect(q('guardrails-mode')?.getAttribute('aria-describedby')).toContain(
      hint.id,
    );
  });

  // Decision 63a: each control's name is a 14px semibold sub-heading.
  it('titles each check card with an xs section header', async () => {
    await render();
    const title = q('guardrail-check-pii')?.querySelector('h4');
    expect(title?.textContent).toBe('PII');
    expect(title?.className.split(' ')).toEqual(
      expect.arrayContaining(['text-foreground', 'text-sm', 'font-semibold']),
    );
  });

  it('renders each check as a small-padded Card', async () => {
    await render();
    const card = q('guardrail-check-pii');
    expect(card?.dataset.slot).toBe('card');
    expect(card?.dataset.padding).toBe('sm');
  });

  it('shows PII entities as toggle chips', async () => {
    await render();
    await act(async () => {
      q('guardrail-configure-pii-input')?.click();
    });
    expect(q('guardrail-pii-EMAIL')?.dataset.variant).toBe('secondary');
    expect(q('guardrail-pii-PHONE')?.dataset.variant).toBe('ghost-muted');
  });

  it('shows a failed catalog load as a destructive empty state with Retry', async () => {
    getGuardrailCatalog.mockReset();
    getGuardrailCatalog.mockRejectedValueOnce(new Error('network'));
    getGuardrailCatalog.mockResolvedValue({
      json: async () => ({ success: true, ...catalog }),
    });
    await render();

    const errorState = () =>
      container.querySelector<HTMLElement>(
        '[data-slot="empty-state"][data-tone="destructive"]',
      );
    expect(errorState()?.textContent).toContain(
      'agents.form.guardrails.loadError',
    );
    expect(errorState()?.dataset.size).toBe('sm');
    const retry = Array.from(errorState()!.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    );

    await act(async () => retry!.click());

    expect(getGuardrailCatalog).toHaveBeenCalledTimes(2);
    expect(errorState()).toBeNull();
  });
});
