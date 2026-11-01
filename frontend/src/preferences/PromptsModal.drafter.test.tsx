import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DrafterEvent, DrafterRequest } from '../drafter/drafterApi';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'count' in options
        ? `${key}:${options.count}`
        : options && 'number' in options
          ? `${key}:${options.number}`
          : key,
  }),
}));
vi.mock('react-router-dom', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      Promise.resolve({ json: () => Promise.resolve({ success: false }) }),
  },
}));

const drafter = vi.hoisted(() => ({
  config: null as null | { enabled: boolean },
  scripts: [] as DrafterEvent[][],
  requests: [] as DrafterRequest[],
}));
vi.mock('../drafter/useDrafterConfig', () => ({
  useDrafterConfig: () => drafter.config,
}));
vi.mock('../drafter/drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../drafter/drafterApi')>()),
  streamDrafter: async (
    request: DrafterRequest,
    _token: string | null,
    onEvent: (event: DrafterEvent) => void,
  ) => {
    drafter.requests.push(JSON.parse(JSON.stringify(request)));
    (drafter.scripts.shift() ?? [{ type: 'end' }]).forEach(onEvent);
  },
}));

import PromptsModal from './PromptsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const ORIGINAL =
  'You answer questions for Meridian.\nToday is {{ system.date }}.\nBe brief.';

const IMPROVE = {
  mode: 'improve',
  message: 'Removed the date and added a price rule.',
  edits: [
    {
      id: 'e1',
      find: 'Today is {{ system.date }}.\n',
      replace: '',
      reason: 'DocsGPT adds the date.',
    },
    {
      id: 'e2',
      find: 'Be brief.',
      replace: 'Be brief. Never quote prices.',
      reason: 'You asked.',
    },
  ],
  result: 'You answer questions for Meridian.\nBe brief. Never quote prices.',
  template_mode: { before: true, after: false },
  warnings: [],
  checks: ['to_persona'],
};

const proposal = (payload: object): DrafterEvent[] => [
  { type: 'status', step: 'drafting' },
  { type: 'proposal', proposal: payload },
  { type: 'end' },
];

type HostProps = {
  type?: 'ADD' | 'EDIT';
  content?: string;
  promptType?: string;
  readOnly?: boolean;
  onDuplicate?: () => void;
  usedBy?: number;
  agent?: { sources: string[]; tools: string[]; agent_type: string };
};

const state = { name: '', content: '' };

function Host({
  type = 'EDIT',
  content = ORIGINAL,
  promptType = 'private',
  readOnly = false,
  onDuplicate,
  usedBy = 0,
  agent,
}: HostProps) {
  const [name, setName] = useState(type === 'EDIT' ? 'Support' : '');
  const [text, setText] = useState(content);
  state.name = name;
  state.content = text;
  return (
    <PromptsModal
      existingPrompts={[]}
      modalState="ACTIVE"
      setModalState={() => undefined}
      type={type}
      newPromptName={name}
      setNewPromptName={setName}
      newPromptContent={text}
      setNewPromptContent={setText}
      editPromptName={name}
      setEditPromptName={setName}
      editPromptContent={text}
      setEditPromptContent={setText}
      currentPromptEdit={{
        name: 'Support',
        id: 'p1',
        type: promptType,
        used_by: { agents: [], others: usedBy },
      }}
      readOnly={readOnly}
      onDuplicate={onDuplicate}
      drafterAgent={agent}
    />
  );
}

describe('PromptsModal drafter', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    drafter.config = { enabled: true };
    drafter.scripts = [];
    drafter.requests = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (props: HostProps = {}) => {
    await act(async () => root.render(<Host {...props} />));
  };
  const askInput = () =>
    document.body.querySelector<HTMLInputElement>(
      'input[aria-label="drafter.prompt.askLabel"]',
    );
  const button = (label: string) =>
    [...document.body.querySelectorAll<HTMLButtonElement>('button')].find(
      (b) => b.textContent === label || b.getAttribute('aria-label') === label,
    );
  const click = async (label: string) => {
    const target = button(label);
    expect(target, label).toBeTruthy();
    await act(async () => target!.click());
  };
  const ask = async (text: string, label = 'drafter.improve') => {
    const input = askInput()!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await click(label);
  };
  const textarea = () =>
    document.body.querySelector<HTMLTextAreaElement>(
      '#edit-prompt-content, #new-prompt-content',
    );

  describe('ask bar', () => {
    it('is hidden while the drafter is off', async () => {
      drafter.config = { enabled: false };
      await render();
      expect(askInput()).toBeNull();
    });

    it('improves an existing prompt', async () => {
      await render();
      expect(askInput()).toBeTruthy();
      expect(button('drafter.improve')).toBeTruthy();
    });

    it('writes an empty new prompt and improves a filled one', async () => {
      await render({ type: 'ADD', content: '' });
      expect(button('drafter.prompt.write')).toBeTruthy();
      expect(askInput()?.placeholder).toBe('drafter.prompt.writePlaceholder');
      act(() => root.unmount());
      root = createRoot(container);
      await render({ type: 'ADD', content: 'Some text' });
      expect(button('drafter.improve')).toBeTruthy();
    });

    it('offers to improve a copy of a prompt the caller cannot change', async () => {
      const onDuplicate = vi.fn();
      await render({ promptType: 'public', onDuplicate });
      expect(askInput()).toBeNull();
      await click('drafter.prompt.improveCopy');
      expect(onDuplicate).toHaveBeenCalledTimes(1);
    });

    it('shows nothing on a read-only prompt without Duplicate', async () => {
      await render({ readOnly: true });
      expect(askInput()).toBeNull();
      expect(button('drafter.prompt.improveCopy')).toBeUndefined();
    });

    it('sends the prompt and the agent it is used on', async () => {
      drafter.scripts = [proposal(IMPROVE)];
      const agent = { sources: ['s1'], tools: ['t1'], agent_type: 'research' };
      await render({ agent });
      await ask('Stop quoting prices');
      expect(drafter.requests[0]).toEqual({
        recipe: 'prompt',
        messages: [{ role: 'user', content: 'Stop quoting prices' }],
        context: {
          mode: 'improve',
          prompt: { id: 'p1', name: 'Support', content: ORIGINAL },
          agent,
        },
      });
    });

    it('notes a save changes every agent using the prompt', async () => {
      await render({ usedBy: 3 });
      expect(document.body.textContent).toContain('drafter.prompt.usedBy:3');
    });

    it('shows a failed draft with Try again', async () => {
      drafter.scripts = [
        [{ type: 'error', code: 'invalid_output' }, { type: 'end' }],
      ];
      await render();
      await ask('Shorter');
      expect(document.body.textContent).toContain(
        'drafter.errors.invalid_output.title',
      );
      expect(button('drafter.retry')).toBeTruthy();
    });
  });

  describe('improve review', () => {
    it('replaces the text with the changes and their reasons', async () => {
      drafter.scripts = [proposal(IMPROVE)];
      await render();
      await ask('Stop quoting prices');
      expect(textarea()).toBeNull();
      const review = document.body.querySelector('[data-slot="prompt-review"]');
      expect(review?.querySelectorAll('del')).toHaveLength(2);
      expect(review?.querySelector('ins')?.textContent).toContain(
        'Never quote prices.',
      );
      expect(review?.textContent).toContain('DocsGPT adds the date.');
      // Leaving template mode is said in the user's language.
      expect(document.body.textContent).toContain(
        'drafter.prompt.checks.to_persona',
      );
      expect(button('modals.prompts.save')).toBeUndefined();
      expect(button('drafter.prompt.acceptAll')).toBeTruthy();
    });

    it('accepts one change and rejects the other', async () => {
      drafter.scripts = [proposal(IMPROVE)];
      await render();
      await ask('Stop quoting prices');
      await click('drafter.prompt.acceptChange:1');
      expect(state.content).toBe(
        'You answer questions for Meridian.\nBe brief.',
      );
      await click('drafter.prompt.rejectChange:2');
      // Every change chosen: the text is back, drafted, and Save returns.
      expect(textarea()?.value).toBe(
        'You answer questions for Meridian.\nBe brief.',
      );
      expect(
        document.body.querySelector('[data-slot="drafted-badge"]'),
      ).toBeTruthy();
      expect(button('modals.prompts.save')).toBeTruthy();
    });

    it('accepts all, and undo puts the original back', async () => {
      drafter.scripts = [proposal(IMPROVE)];
      await render();
      await ask('Stop quoting prices');
      await click('drafter.prompt.acceptAll');
      expect(state.content).toBe(IMPROVE.result);
      await click('drafter.undoField');
      expect(state.content).toBe(ORIGINAL);
      expect(
        document.body.querySelector('[data-slot="drafted-badge"]'),
      ).toBeNull();
    });

    it('discards the review', async () => {
      drafter.scripts = [proposal(IMPROVE)];
      await render();
      await ask('Stop quoting prices');
      await click('drafter.prompt.acceptChange:1');
      await click('drafter.prompt.discard');
      expect(state.content).toBe(ORIGINAL);
      expect(textarea()?.value).toBe(ORIGINAL);
      expect(
        document.body.querySelector('[data-slot="drafted-badge"]'),
      ).toBeNull();
    });

    it('reviews one by one', async () => {
      drafter.scripts = [proposal(IMPROVE)];
      await render();
      await ask('Stop quoting prices');
      await click('drafter.prompt.reviewOneByOne');
      const current = () =>
        document.body
          .querySelector('[data-edit-id][data-current]')
          ?.getAttribute('data-edit-id');
      expect(current()).toBe('e1');
      expect(button('drafter.prompt.reviewOneByOne')).toBeUndefined();
      await click('drafter.prompt.rejectChange:1');
      expect(current()).toBe('e2');
      await click('drafter.prompt.acceptChange:2');
      expect(state.content).toBe(
        'You answer questions for Meridian.\nToday is {{ system.date }}.\nBe brief. Never quote prices.',
      );
      expect(document.body.querySelector('[data-slot="prompt-review"]')).toBe(
        null,
      );
    });
  });

  describe('write', () => {
    it('fills the name and text, each drafted with undo', async () => {
      drafter.scripts = [
        proposal({
          mode: 'write',
          message: 'Wrote an HR helper.',
          name: 'HR handbook assistant',
          content: 'You help employees with the HR handbook.',
          reason: 'A plain persona.',
          warnings: [],
          checks: [],
        }),
      ];
      await render({ type: 'ADD', content: '' });
      await ask('An HR handbook helper', 'drafter.prompt.write');
      expect(drafter.requests[0].context).toMatchObject({
        mode: 'write',
        prompt: { id: null, name: '', content: '' },
        agent: null,
      });
      expect(state.name).toBe('HR handbook assistant');
      expect(state.content).toBe('You help employees with the HR handbook.');
      expect(
        document.body.querySelectorAll('[data-slot="drafted-badge"]'),
      ).toHaveLength(2);
      expect(document.body.textContent).toContain(
        'Wrote an HR helper. A plain persona.',
      );
      const undoName = document.body.querySelector<HTMLButtonElement>(
        '[data-slot="drafted-badge"] button',
      )!;
      await act(async () => undoName.click());
      expect(state.name).toBe('');
      expect(state.content).toBe('You help employees with the HR handbook.');
    });
  });
});
