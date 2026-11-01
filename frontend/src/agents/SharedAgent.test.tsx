import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Each selector reads its own value; anything unset reads null.
const redux = vi.hoisted(() => ({
  values: new Map<unknown, unknown>(),
  dispatch: vi.fn(),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: unknown) => redux.values.get(selector) ?? null,
  useDispatch: () => redux.dispatch,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-router-dom', () => ({
  useParams: () => ({ agentId: 'share-token' }),
}));

// The composer as the page drives it: what it was handed, and its submit.
type ComposerProps = {
  onSubmit: (text: string) => void;
  queuedQuestion?: string | null;
  onQueuedQuestionConsumed?: () => void;
};
const composer = vi.hoisted(() => ({ props: null as unknown }));
vi.mock('../components/MessageInput', () => ({
  default: (props: unknown) => {
    composer.props = props;
    return null;
  },
}));
vi.mock('../conversation/ConversationMessages', () => ({
  default: (props: {
    starters?: string[];
    handleQuestion: (args: { question: string }) => void;
    onOpenArtifact?: (request: {
      id: string;
      toolName: string;
      version?: number;
    }) => void;
  }) => (
    <div data-testid="messages">
      {/* A starter, as the empty chat's AgentStarters sends it. */}
      {props.starters?.map((starter) => (
        <button
          key={starter}
          type="button"
          data-testid="starter"
          onClick={() => props.handleQuestion({ question: starter })}
        >
          {starter}
        </button>
      ))}
      {props.onOpenArtifact && (
        <button
          type="button"
          data-testid="open-artifact"
          onClick={() =>
            props.onOpenArtifact?.({ id: 'run-file', toolName: '', version: 1 })
          }
        />
      )}
    </div>
  ),
}));
vi.mock('../components/ArtifactPanel', () => ({
  default: (props: { artifactId: string }) => (
    <div data-testid="artifact-panel">{props.artifactId}</div>
  ),
}));
vi.mock('./SharedAgentCard', () => ({ default: () => null }));
vi.mock('../conversation/conversationSlice', () => ({
  addQuery: vi.fn(),
  fetchAnswer: vi.fn(),
  resendQuery: vi.fn(),
  selectQueries: () => [],
  selectStatus: () => 'idle',
}));

const getSharedAgent = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getSharedAgent: (...args: unknown[]) => getSharedAgent(...args),
  },
}));

import SharedAgent from './SharedAgent';
import { addQuery } from '../conversation/conversationSlice';
import { selectAttachments, type Attachment } from '../upload/uploadSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SharedAgent', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getSharedAgent.mockReset();
    redux.values = new Map();
    redux.dispatch.mockReset();
    vi.mocked(addQuery).mockClear();
    composer.props = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = () => act(async () => root.render(<SharedAgent />));
  const state = () =>
    container.querySelector<HTMLElement>('[data-slot="empty-state"]');

  it('says the agent is not found on a 404', async () => {
    getSharedAgent.mockResolvedValue({ ok: false, status: 404 });
    await render();
    expect(state()?.dataset.tone).toBe('neutral');
    expect(state()?.textContent).toContain('agents.shared.notFound');
    expect(state()?.querySelector('button')).toBeNull();
  });

  it('shows a failed load as an error with Retry, not "not found"', async () => {
    getSharedAgent.mockRejectedValue(new TypeError('Failed to fetch'));
    await render();
    expect(state()?.dataset.tone).toBe('destructive');
    expect(state()?.textContent).toContain('agents.shared.loadError');
    expect(state()?.textContent).not.toContain('agents.shared.notFound');

    getSharedAgent.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'a1', name: 'Vendor Due Diligence' }),
    });
    const retry = Array.from(state()!.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(getSharedAgent).toHaveBeenCalledTimes(2);
    expect(state()).toBeNull();
    expect(container.textContent).toContain('Vendor Due Diligence');
  });

  it('treats a 500 as a failed load too', async () => {
    getSharedAgent.mockResolvedValue({ ok: false, status: 500 });
    await render();
    expect(state()?.dataset.tone).toBe('destructive');
  });

  // The runner owns the run, so its files open here as they do in the chat.
  it("opens an answer's artifact in a side panel", async () => {
    getSharedAgent.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'a1', name: 'Vendor Due Diligence' }),
    });
    await render();
    const open = container.querySelector<HTMLButtonElement>(
      '[data-testid="open-artifact"]',
    );
    expect(open).not.toBeNull();
    await act(async () => open!.click());
    const panel = document.querySelector('[data-testid="artifact-panel"]');
    expect(panel?.textContent).toBe('run-file');
    expect(panel?.closest('[role="dialog"]')).not.toBeNull();
  });

  // Sending now would go without the file still uploading; the composer's
  // armed send waits for it instead.
  it('queues a starter into the composer while a file uploads, then sends it', async () => {
    const question = 'Which carriers renew this month?';
    const file = (status: Attachment['status']): Attachment => ({
      id: 'a1',
      fileName: 'rates.pdf',
      progress: status === 'completed' ? 100 : 40,
      status,
      taskId: 't1',
      attachmentId: 'att-1',
    });
    const props = () => composer.props as ComposerProps;
    redux.values.set(selectAttachments, [file('uploading')]);
    getSharedAgent.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'a1', name: 'Vendor', starters: [question] }),
    });
    await render();
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="starter"]')!
        .click(),
    );
    expect(addQuery).not.toHaveBeenCalled();
    expect(props().queuedQuestion).toBe(question);

    await act(async () => props().onQueuedQuestionConsumed?.());
    expect(props().queuedQuestion).toBeNull();

    // The file is ready: the composer flushes the armed question.
    redux.values.set(selectAttachments, [file('completed')]);
    await render();
    await act(async () => props().onSubmit(question));
    expect(addQuery).toHaveBeenCalledWith({ prompt: question });
  });
});
