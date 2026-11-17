import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const paused = {
  prompt: 'write the QBR deck',
  tool_calls: [
    {
      tool_name: 'ask_user',
      action_name: 'ask_user',
      call_id: 'ask-1',
      arguments: {},
      status: 'awaiting_answer',
      message: 'Two things change what goes in it:',
      questions: [{ id: 'q1', text: 'Which quarter?', options: [] }],
    },
  ],
};
const state = {
  preference: { token: null, selectedAgent: null, agents: [] },
  conversation: {
    conversationId: 'conv-1',
    queries: [paused] as unknown[],
    status: 'awaiting_tool_actions',
  },
  upload: { attachments: [] as unknown[] },
};
const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: typeof state) => unknown) => selector(state),
  useDispatch: () => dispatch,
}));
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ conversationId: 'conv-1' }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
// The composer reports what it was given and sends what the test types.
const composer = vi.hoisted(() => ({
  props: null as null | {
    onSubmit: (text: string) => void;
    placeholder?: string;
  },
}));
vi.mock('../components/MessageInput', () => ({
  default: (props: { onSubmit: (text: string) => void }) => {
    composer.props = props;
    return null;
  },
}));
vi.mock('../components/ArtifactPanel', () => ({ default: () => null }));
vi.mock('./ArtifactsPanel', () => ({ default: () => null }));
vi.mock('./SourcesPanel', () => ({ default: () => null }));
vi.mock('./ConversationMessages', () => ({ default: () => null }));
vi.mock('./conversationSlice', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./conversationSlice')>()),
  fetchAnswer: (arg: unknown) => ({ type: 'fetchAnswer', payload: arg }),
  loadConversation: (arg: unknown) => ({ type: 'load', payload: arg }),
  resumeQuestion: (arg: unknown) => ({ type: 'resumeQuestion', payload: arg }),
}));

import Conversation from './Conversation';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  dispatch.mockReset();
  state.conversation.queries = [paused];
  state.upload.attachments = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const sent = (type: string) =>
  dispatch.mock.calls.map(([action]) => action).filter((a) => a?.type === type);

describe('Conversation, a turn paused on questions', () => {
  it('asks the composer for a typed answer and resumes with it', async () => {
    await act(async () => root.render(<Conversation />));
    expect(composer.props?.placeholder).toBe('questions.typeAnswer');
    await act(async () => composer.props!.onSubmit('  Q3, for their team '));
    expect(sent('resumeQuestion')).toEqual([
      {
        type: 'resumeQuestion',
        payload: { callId: 'ask-1', action: { answer: 'Q3, for their team' } },
      },
    ]);
    // Not a new turn: no question bubble, no new request.
    expect(sent('fetchAnswer')).toEqual([]);
    expect(
      dispatch.mock.calls.some(([a]) => a?.type === 'conversation/addQuery'),
    ).toBe(false);
  });

  it('keeps the usual prompt once nothing waits', async () => {
    state.conversation.queries = [{ prompt: 'hi', response: 'Hello.' }];
    await act(async () => root.render(<Conversation />));
    expect(composer.props?.placeholder).toBeUndefined();
  });
});
