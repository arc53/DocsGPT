import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const getApproval = vi.fn();
const decideApproval = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values?.decision
        ? `${key}:${values.decision}`
        : values?.comment
          ? `${key}:${values.comment}`
          : values?.date
            ? `${key}:${values.date}`
            : key,
  }),
}));
vi.mock('@/hooks', () => ({ useDarkTheme: () => [false] }));
vi.mock('@/api/services/monitorsService', () => ({
  default: {
    getApproval: (...args: unknown[]) => getApproval(...args),
    decideApproval: (...args: unknown[]) => decideApproval(...args),
  },
}));

import ApprovalPage from './ApprovalPage';
import type { ApprovalView } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const view = (overrides: Partial<ApprovalView> = {}): ApprovalView => ({
  question: 'Send the announcement?',
  details: 'Draft line one\nDraft line two',
  options: ['approve', 'reject'],
  allow_comment: true,
  expires_at: null,
  decided: false,
  decision: null,
  decided_at: null,
  waiting: true,
  ...overrides,
});

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('ApprovalPage', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getApproval.mockReset();
    decideApproval.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async () => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/approve/apv_token_123']}>
          <Routes>
            <Route path="/approve/:token" element={<ApprovalPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const buttons = () =>
    Array.from(container.querySelectorAll('button')).filter((b) =>
      b.textContent?.startsWith('approval.options.'),
    );

  it('says when the request expires', async () => {
    getApproval.mockResolvedValue({
      state: 'ok',
      view: view({ expires_at: '2026-10-08T09:30:00Z' }),
    });
    await render();
    expect(container.textContent).toContain('approval.expiresAt:');
  });

  it('opening the page only reads the request', async () => {
    getApproval.mockResolvedValue({ state: 'ok', view: view() });
    await render();
    expect(getApproval).toHaveBeenCalledWith('apv_token_123');
    expect(decideApproval).not.toHaveBeenCalled();
    expect(container.textContent).toContain('Send the announcement?');
    expect(
      container.querySelector('[data-testid="approval-details"]')?.textContent,
    ).toBe('Draft line one\nDraft line two');
    expect(buttons().map((b) => b.textContent)).toEqual([
      'approval.options.approve',
      'approval.options.reject',
    ]);
  });

  it('a button posts the decision with the comment once', async () => {
    getApproval.mockResolvedValue({ state: 'ok', view: view() });
    decideApproval.mockResolvedValue({ state: 'decided', decision: 'approve' });
    await render();
    const textarea = container.querySelector('textarea')!;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        'value',
      )!.set!;
      setter.call(textarea, 'Looks good');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    act(() => buttons()[0].click());
    await flush();
    expect(decideApproval).toHaveBeenCalledTimes(1);
    expect(decideApproval).toHaveBeenCalledWith(
      'apv_token_123',
      'approve',
      'Looks good',
    );
    expect(container.textContent).toContain(
      'approval.thanks:approval.options.approve',
    );
    // The confirmation repeats what this visitor wrote, in a success style.
    expect(
      container.querySelector('[data-testid="approval-sent-comment"]')
        ?.textContent,
    ).toBe('approval.yourComment:Looks good');
    expect(
      container
        .querySelector('[data-slot="alert"]')
        ?.getAttribute('data-variant'),
    ).toBe('success');
    expect(buttons()).toHaveLength(0);
  });

  it('shows a decision already made instead of the buttons', async () => {
    getApproval.mockResolvedValue({
      state: 'ok',
      view: view({ decided: true, decision: 'reject', waiting: false }),
    });
    await render();
    expect(buttons()).toHaveLength(0);
    expect(container.textContent).toContain(
      'approval.alreadyDecided:approval.options.reject',
    );
    // Someone else's earlier decision is information, not this visitor's success.
    expect(
      container
        .querySelector('[data-slot="alert"]')
        ?.getAttribute('data-variant'),
    ).toBe('info');
  });

  it('keeps custom options as written and hides the comment when not allowed', async () => {
    getApproval.mockResolvedValue({
      state: 'ok',
      view: view({ options: ['Ship', 'Hold'], allow_comment: false }),
    });
    await render();
    const labels = Array.from(container.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(labels).toEqual(expect.arrayContaining(['Ship', 'Hold']));
    expect(container.querySelector('textarea')).toBeNull();
  });

  it('a link that no longer works says so', async () => {
    getApproval.mockResolvedValue({ state: 'missing' });
    await render();
    expect(container.textContent).toContain('approval.missingTitle');
    expect(container.querySelector('button')).toBeNull();
  });

  it('a 409 on press shows the earlier decision', async () => {
    getApproval.mockResolvedValue({ state: 'ok', view: view() });
    decideApproval.mockResolvedValue({ state: 'already', decision: 'reject' });
    await render();
    act(() => buttons()[0].click());
    await flush();
    expect(container.textContent).toContain(
      'approval.alreadyDecided:approval.options.reject',
    );
  });

  it('a failed press keeps the buttons and says it failed', async () => {
    getApproval.mockResolvedValue({ state: 'ok', view: view() });
    decideApproval.mockResolvedValue({ state: 'error' });
    await render();
    act(() => buttons()[1].click());
    await flush();
    expect(container.textContent).toContain('approval.submitError');
    expect(buttons()).toHaveLength(2);
  });
});
