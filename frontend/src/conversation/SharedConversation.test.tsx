import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const state = {
  sharedConversation: {
    queries: [],
    title: 'Shared chat',
    date: '',
    apiKey: null,
    status: 'idle',
  },
  preference: { token: null },
  upload: { attachments: [] },
  workspace: { current: 'personal' },
};

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: typeof state) => unknown) => selector(state),
  useDispatch: () => vi.fn(),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../api/services/conversationService', () => ({
  default: { getSharedConversation: () => new Promise(() => {}) },
}));
vi.mock('../components/MessageInput', () => ({ default: () => null }));
vi.mock('./ConversationMessages', () => ({ default: () => null }));

import { SharedConversation } from './SharedConversation';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SharedConversation', () => {
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
  });

  it('asks search engines not to index the share', () => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/share/abc']}>
          <Routes>
            <Route path="/share/:identifier" element={<SharedConversation />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(
      document.head.querySelector<HTMLMetaElement>('meta[name="robots"]')
        ?.content,
    ).toBe('noindex, nofollow');
  });
});
