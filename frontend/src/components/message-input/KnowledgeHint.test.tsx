import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import KnowledgeHint from './KnowledgeHint';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('KnowledgeHint', () => {
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

  const render = async (props: Partial<Parameters<typeof KnowledgeHint>[0]>) =>
    act(async () =>
      root.render(
        <KnowledgeHint
          readsRest={true}
          pending={false}
          error={null}
          onAdd={() => undefined}
          {...props}
        />,
      ),
    );

  it('says the model reads the rest on demand when it can', async () => {
    await render({ readsRest: true });
    expect(container.textContent).toContain(
      'conversation.attachments.knowledgeHint',
    );
    expect(container.textContent).not.toContain('knowledgeHintNoTools');
  });

  it('says some files are left out for a model without tools', async () => {
    await render({ readsRest: false });
    expect(container.textContent).toContain(
      'conversation.attachments.knowledgeHintNoTools',
    );
  });

  it('runs the action from its button', async () => {
    const onAdd = vi.fn();
    await render({ onAdd });
    const button = container.querySelector('button');
    expect(button?.textContent).toContain(
      'conversation.attachments.addToKnowledge',
    );
    await act(async () => button?.click());
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it('marks the button busy while the request runs', async () => {
    await render({ pending: true });
    const button = container.querySelector('button');
    expect(button?.disabled).toBe(true);
    expect(button?.getAttribute('aria-busy')).toBe('true');
  });

  it('shows a refused request inline', async () => {
    await render({ error: 'Could not add' });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toBe('Could not add');
  });
});
