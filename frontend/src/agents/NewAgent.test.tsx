import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockState = {
  preference: {
    token: null,
    sourceDocs: [],
    selectedAgent: null,
    prompts: [],
    agentFolders: [],
  },
};

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(mockState),
  useDispatch: () => vi.fn(),
}));

const jsonResponse = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      jsonResponse({
        tools: [
          {
            id: 'tool-1',
            name: 'remote_device',
            display_name: 'Laptop',
            config: { device_id: 'device-1' },
          },
        ],
      }),
    getAgentFolders: () => jsonResponse({ folders: [] }),
    getAgent: () => jsonResponse({}),
    createAgent: () => jsonResponse({ message: 'Name is taken' }, false),
    updateAgent: () => jsonResponse({}),
    deleteAgent: () => jsonResponse({}),
    createPrompt: () => jsonResponse({}),
  },
}));

vi.mock('../api/services/devicesService', () => ({
  default: {
    list: () =>
      Promise.resolve({
        devices: [{ id: 'device-1', last_seen_at: new Date().toISOString() }],
      }),
  },
}));

vi.mock('../api/services/modelService', () => ({
  default: {
    getModels: () => jsonResponse({ models: [] }),
    transformModels: () => [],
  },
}));

// The pickers render only their trigger here, plus each item's rich
// description so the device status pill can be checked.
vi.mock('../components/MultiSelectPopover', () => ({
  MultiSelectPopover: ({
    trigger,
    items,
  }: {
    trigger: React.ReactNode;
    items: MultiSelectPopoverItem[];
  }) => (
    <div data-testid="picker">
      {trigger}
      {items.map((item) => (
        <div key={item.id}>{item.descriptionNode}</div>
      ))}
    </div>
  ),
}));

vi.mock('./workflow/WorkflowBuilder', () => ({ default: () => null }));
vi.mock('./AgentPreview', () => ({ default: () => null }));
vi.mock('../settings/Prompts', () => ({ default: () => null }));
vi.mock('./components/GuardrailsSection', () => ({
  default: () => null,
  guardrailsIncomplete: () => false,
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../modals/AgentDetailsModal', () => ({ default: () => null }));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../preferences/PromptsModal', () => ({ default: () => null }));
vi.mock('../navigation/SectionPills', () => ({ default: () => null }));
vi.mock('../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => null,
}));
vi.mock('../components/FileUpload', () => ({ FileUpload: () => null }));
vi.mock('../components/SourcesPopoverFooter', () => ({ default: () => null }));
vi.mock('../components/ToolIcon', () => ({ default: () => null }));

import NewAgent from './NewAgent';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const setNativeValue = (
  el: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) => {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('NewAgent form', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <NewAgent mode="new" />
        </MemoryRouter>,
      );
    });
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes(text),
    )!;

  // Decision 63 (3): every field, picker and button in the form is 42px.
  it('renders the name field as a default-size (42px) pill Input', async () => {
    await render();
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    expect(name.getAttribute('data-slot')).toBe('input');
    expect(name.getAttribute('data-size')).toBe('default');
    expect(name.getAttribute('data-shape')).toBe('pill');
  });

  it('renders the Add prompt button at the field height', async () => {
    await render();
    const add = buttonByText('agents.form.buttons.add');
    expect(add.getAttribute('data-variant')).toBe('outline-primary');
    expect(add.getAttribute('data-size')).toBe('field');
    expect(add.getAttribute('data-shape')).toBe('pill');
  });

  it('renders the token and request limits as default-size pill Inputs', async () => {
    await render();
    await act(async () =>
      buttonByText('agents.form.sections.advanced').click(),
    );
    for (const key of ['enterTokenLimit', 'enterRequestLimit']) {
      const field = container.querySelector(
        `input[placeholder="agents.form.placeholders.${key}"]`,
      )!;
      expect(field.getAttribute('data-size')).toBe('default');
      expect(field.getAttribute('data-shape')).toBe('pill');
    }
  });

  it('titles each form panel with a SectionHeader spaced by the panel gap', async () => {
    await render();
    const titles = Array.from(
      container.querySelectorAll('[data-slot="section-header"] > h2'),
    ).map((h) => h.textContent);
    expect(titles).toEqual(
      expect.arrayContaining([
        'agents.form.sections.meta',
        'agents.form.sections.source',
        'agents.form.sections.tools',
        'agents.form.sections.agentType',
        'agents.form.sections.models',
      ]),
    );
    const meta = Array.from(
      container.querySelectorAll('[data-slot="section-header"]'),
    ).find((h) => h.textContent === 'agents.form.sections.meta')!;
    expect(meta.parentElement!.className.split(' ')).toEqual(
      expect.arrayContaining(['flex', 'flex-col', 'gap-5']),
    );
    expect((meta.nextElementSibling as HTMLElement).className).not.toContain(
      'mt-5',
    );
  });

  // Decision 64: the Advanced header is a section-toggle with a leading
  // lucide chevron; the panel draws the focus ring.
  it('renders the Advanced header as a section-toggle', async () => {
    await render();
    const toggle = buttonByText('agents.form.sections.advanced');
    expect(toggle.getAttribute('data-variant')).toBe('section-toggle');
    expect(toggle.getAttribute('data-size')).toBe('sm');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const chevron = toggle.firstElementChild!;
    expect(chevron.matches('svg.lucide-chevron-right')).toBe(true);
    expect(chevron.getAttribute('class')).not.toContain('rotate-90');
    expect(toggle.querySelectorAll('svg')).toHaveLength(1);
    expect(toggle.querySelector('h2')).toBeNull();
    expect(toggle.parentElement!.tagName).toBe('H2');
    const panel = toggle.closest('.bg-card')!;
    expect(panel.className).toContain(
      'has-[[data-variant=section-toggle]:focus-visible]:ring-3',
    );

    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(chevron.getAttribute('class')).toContain('rotate-90');
  });

  it('renders the description as a large ui Textarea', async () => {
    await render();
    const description = container.querySelector(
      'textarea[placeholder="agents.form.placeholders.describeAgent"]',
    )!;
    expect(description.getAttribute('data-slot')).toBe('textarea');
    expect(description.getAttribute('data-size')).toBe('lg');
  });

  it('renders the pickers as pill comboboxes, muted while empty', async () => {
    await render();
    const triggers = Array.from(
      container.querySelectorAll('[data-testid="picker"] > button'),
    );
    // Sources, tools, models.
    expect(triggers).toHaveLength(3);
    for (const trigger of triggers) {
      expect(trigger.getAttribute('data-variant')).toBe('combobox');
      expect(trigger.getAttribute('data-size')).toBe('field');
      expect(trigger.getAttribute('data-shape')).toBe('pill');
      expect(trigger.hasAttribute('data-placeholder')).toBe(true);
      expect(trigger.querySelector('span.truncate')).not.toBeNull();
    }
  });

  it('shows the device status as a Badge', async () => {
    await render();
    const badge = container.querySelector('[data-slot="badge"]');
    expect(badge?.textContent).toBe('settings.devices.online');
    expect(badge?.getAttribute('data-variant')).toBe('success');
  });

  it('renders Save draft and Publish as pill button variants', async () => {
    await render();
    const draft = buttonByText('agents.form.buttons.saveDraft');
    expect(draft.getAttribute('data-variant')).toBe('outline-primary');
    expect(draft.getAttribute('data-shape')).toBe('pill');
    const publish = buttonByText('agents.form.buttons.publish');
    expect(publish.getAttribute('data-variant')).toBe('default');
    expect(publish.getAttribute('data-shape')).toBe('pill');
    expect(publish.disabled).toBe(true);
  });

  // Item 42: the header's Cancel (shown once the form is dirty) is ghost.
  it('renders the header Cancel as a ghost pill once the form changes', async () => {
    await render();
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="agents.form.placeholders.agentName"]',
    )!;
    await act(async () => setNativeValue(name, 'Support bot'));
    const cancel = buttonByText('agents.form.buttons.cancel');
    expect(cancel.getAttribute('data-variant')).toBe('ghost');
    expect(cancel.getAttribute('data-shape')).toBe('pill');
  });

  it('shows a failed save as a destructive alert with an icon', async () => {
    await render();
    const draft = buttonByText('agents.form.buttons.saveDraft');
    await act(async () => draft.click());
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('Name is taken');
    // ui/alert's destructive variant.
    expect(alert.className).toContain('border-destructive/50');
    expect(alert.className).toContain('bg-destructive/10');
    expect(alert.querySelector('svg.lucide-circle-x')).not.toBeNull();
    // Decision 69 (b): the notice sits above the form panel, not in the
    // header's button row.
    expect(draft.parentElement?.contains(alert)).toBe(false);
  });

  it('marks JSON schema validity with token colours and lucide icons', async () => {
    await render();
    await act(async () =>
      buttonByText('agents.form.sections.advanced').click(),
    );
    const schema = Array.from(container.querySelectorAll('textarea')).find(
      (el) => el.className.includes('font-mono'),
    )!;
    expect(schema.getAttribute('data-slot')).toBe('textarea');
    expect(schema.getAttribute('data-size')).toBe('lg');

    await act(async () => setNativeValue(schema, '{ not json'));
    const invalid = Array.from(container.querySelectorAll('div')).find(
      (el) => el.textContent === 'agents.form.advanced.invalidJson',
    )!;
    expect(invalid.className).toContain('text-destructive');
    expect(invalid.querySelector('svg.lucide-circle-x')).not.toBeNull();

    await act(async () => setNativeValue(schema, '{}'));
    const valid = Array.from(container.querySelectorAll('div')).find(
      (el) => el.textContent === 'agents.form.advanced.validJson',
    )!;
    expect(valid.className).toContain('text-success');
    expect(valid.querySelector('svg.lucide-circle-check')).not.toBeNull();
  });

  it('shows the preview placeholder illustration as decorative images', async () => {
    await render();
    const images = container.querySelectorAll('img[alt=""]');
    expect(images).toHaveLength(2);
    for (const img of images) {
      expect(img.getAttribute('aria-hidden')).toBe('true');
    }
  });
});
