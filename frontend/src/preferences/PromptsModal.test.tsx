import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isTablet: false, isDesktop: true }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
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

import PromptsModal from './PromptsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('PromptsModal', () => {
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

  const render = async () => {
    await act(async () => {
      root.render(
        <PromptsModal
          existingPrompts={[]}
          modalState="ACTIVE"
          setModalState={() => undefined}
          type="ADD"
          newPromptName=""
          setNewPromptName={() => undefined}
          newPromptContent="Hello {{ source.content }}"
          setNewPromptContent={() => undefined}
          editPromptName=""
          setEditPromptName={() => undefined}
          editPromptContent=""
          setEditPromptContent={() => undefined}
          currentPromptEdit={{ name: '', id: '', type: '' }}
        />,
      );
    });
  };

  it('edits the prompt text in a large Textarea', async () => {
    await render();
    const textarea = document.body.querySelector<HTMLTextAreaElement>(
      '#new-prompt-content',
    );
    expect(textarea?.dataset.slot).toBe('textarea');
    expect(textarea?.dataset.size).toBe('lg');
  });

  it('scrolls the highlight layer through custom properties, not a transform', async () => {
    await render();
    const layer = document.body.querySelector<HTMLElement>(
      '.prompt-variable-highlight',
    )?.parentElement;
    expect(layer).toBeTruthy();
    expect(layer?.style.transform).toBe('');
    expect(layer?.style.getPropertyValue('--scroll-x')).toBe('0px');
    expect(layer?.style.getPropertyValue('--scroll-y')).toBe('0px');
  });
});
