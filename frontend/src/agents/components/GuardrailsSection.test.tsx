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

  it('uses the pressed-toggle variants for stage chips', async () => {
    await render();
    expect(q('guardrail-stage-pii-input')?.dataset.variant).toBe('secondary');
    const locked = q('guardrail-stage-pii-output');
    expect(locked?.dataset.variant).toBe('secondary');
    expect((locked as HTMLButtonElement).disabled).toBe(true);
    expect(locked?.title).toBe('agents.form.guardrails.lockedByFloor');
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
    expect(orphan?.dataset.variant).toBe('ghost-destructive');
    expect(orphan?.dataset.size).toBe('xs');
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
    expect(mode?.dataset.size).toBe('lg');
    expect(mode?.dataset.shape).toBe('pill');

    await act(async () => {
      q('guardrail-configure-policy-input')?.click();
    });
    expect(q('guardrail-policy-text')?.dataset.slot).toBe('textarea');
  });

  it('shows PII entities as toggle chips', async () => {
    await render();
    await act(async () => {
      q('guardrail-configure-pii-input')?.click();
    });
    expect(q('guardrail-pii-EMAIL')?.dataset.variant).toBe('secondary');
    expect(q('guardrail-pii-PHONE')?.dataset.variant).toBe('ghost-muted');
  });
});
