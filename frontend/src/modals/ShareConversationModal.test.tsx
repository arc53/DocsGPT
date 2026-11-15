import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mocks = vi.hoisted(() => ({ shareConversation: vi.fn() }));

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector({}),
}));

vi.mock('../preferences/preferenceSlice', () => ({
  selectToken: () => null,
  selectChunks: () => '2',
  selectPrompt: () => ({ id: 'default' }),
  selectSelectedDocs: () => null,
  selectSourceDocs: () => [],
}));

vi.mock('../api/services/conversationService', () => ({ default: mocks }));

import { ShareConversationModal } from './ShareConversationModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const respond = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

describe('ShareConversationModal', () => {
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
    mocks.shareConversation.mockReset();
    document.body.innerHTML = '';
  });

  const create = async () => {
    await act(async () => {
      root.render(
        <ShareConversationModal close={() => undefined} conversationId="c1" />,
      );
    });
    const button = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === 'modals.shareConv.create',
    )!;
    await act(async () => button.click());
  };

  it('shows why the server refused the link', async () => {
    mocks.shareConversation.mockReturnValue(
      respond(
        { success: false, message: 'A promptable link can’t use “Handbook”.' },
        false,
      ),
    );
    await create();
    expect(document.body.textContent).toContain(
      'A promptable link can’t use “Handbook”.',
    );
  });

  it('shows the link once it is created', async () => {
    mocks.shareConversation.mockReturnValue(
      respond({ success: true, identifier: 'share-1' }),
    );
    await create();
    expect(document.body.textContent).toContain('/share/share-1');
  });
});
