import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Each selector reads its own value; anything unset reads null.
const redux = vi.hoisted(() => ({
  values: new Map<unknown, unknown>(),
  dispatch: vi.fn(),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: unknown) => redux.values.get(selector) ?? null,
  useDispatch: () => redux.dispatch,
}));

// The composer as the preview drives it: what it was handed, and its submit.
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
  default: () => null,
}));

import AgentPreview from './AgentPreview';
import {
  addQuery,
  selectPreviewQueries,
  selectPreviewStatus,
} from './agentPreviewSlice';
import { selectSelectedAgent } from '../preferences/preferenceSlice';
import { selectAttachments, type Attachment } from '../upload/uploadSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const file = (status: Attachment['status']): Attachment => ({
  id: 'a1',
  fileName: 'rates.pdf',
  progress: status === 'completed' ? 100 : 40,
  status,
  taskId: 't1',
  attachmentId: 'att-1',
});

const QUESTION = 'Which carriers renew this month?';

describe('AgentPreview starters', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    redux.values = new Map<unknown, unknown>([
      [selectPreviewQueries, []],
      [selectPreviewStatus, 'idle'],
      [selectSelectedAgent, { id: 'a1', starters: [QUESTION] }],
      [selectAttachments, []],
    ]);
    redux.dispatch.mockReset();
    composer.props = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = () => act(async () => root.render(<AgentPreview />));
  const props = () => composer.props as ComposerProps;
  const clickStarter = () =>
    act(async () =>
      container
        .querySelector('[data-testid="hero-suggestions"]')!
        .querySelector<HTMLButtonElement>('button')!
        .click(),
    );

  it('sends a starter at once when no file is pending', async () => {
    await render();
    await clickStarter();
    expect(redux.dispatch).toHaveBeenCalledWith(addQuery({ prompt: QUESTION }));
  });

  // Sending now would go without the file still uploading; the composer's
  // armed send waits for it instead.
  it('queues a starter into the composer while a file uploads, then sends it', async () => {
    redux.values.set(selectAttachments, [file('uploading')]);
    await render();
    await clickStarter();
    expect(redux.dispatch).not.toHaveBeenCalled();
    expect(props().queuedQuestion).toBe(QUESTION);

    await act(async () => props().onQueuedQuestionConsumed?.());
    expect(props().queuedQuestion).toBeNull();

    // The file is ready: the composer flushes the armed question.
    redux.values.set(selectAttachments, [file('completed')]);
    await render();
    await act(async () => props().onSubmit(QUESTION));
    expect(redux.dispatch).toHaveBeenCalledWith(addQuery({ prompt: QUESTION }));
  });
});
