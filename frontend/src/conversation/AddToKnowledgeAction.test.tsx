import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const hook = vi.hoisted(() => ({
  addToKnowledge: vi.fn(),
  pending: false,
  error: null as string | null,
}));
vi.mock('../upload/useAddToKnowledge', () => ({
  useAddToKnowledge: () => hook,
}));

import AddToKnowledgeAction from './AddToKnowledgeAction';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AddToKnowledgeAction', () => {
  let container: HTMLDivElement;
  let root: Root;
  const files = [
    { id: 'a1', fileName: 'one.pdf' },
    { id: 'a2', fileName: 'two.pdf' },
  ];

  beforeEach(() => {
    hook.addToKnowledge.mockReset();
    hook.pending = false;
    hook.error = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = () =>
    act(async () => root.render(<AddToKnowledgeAction files={files} />));

  it('adds the turn files to Knowledge and says so', async () => {
    hook.addToKnowledge.mockResolvedValue(true);
    await render();
    const button = container.querySelector('button')!;
    expect(button.textContent).toBe('conversation.attachments.addToKnowledge');

    await act(async () => button.click());

    expect(hook.addToKnowledge).toHaveBeenCalledWith(files);
    expect(container.querySelector('button')).toBeNull();
    expect(container.textContent).toContain(
      'conversation.attachments.knowledgeAdded',
    );
  });

  it('keeps the button when the server refused, with the reason', async () => {
    hook.addToKnowledge.mockResolvedValue(false);
    hook.error = 'conversation.attachments.knowledgeFailed';
    await render();
    await act(async () => container.querySelector('button')!.click());
    expect(container.querySelector('button')).not.toBeNull();
    expect(container.textContent).toContain(
      'conversation.attachments.knowledgeFailed',
    );
  });
});
