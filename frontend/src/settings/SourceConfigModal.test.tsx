import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

vi.mock('../api/services/userService', () => ({
  default: { updateSourceConfig: vi.fn() },
}));

import type { Doc } from '../models/misc';
import SourceConfigModal from './SourceConfigModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (fields: Partial<Doc>): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '',
  model: '',
  ...fields,
});

describe('SourceConfigModal access', () => {
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
    document.body.innerHTML = '';
  });

  const render = async (document: Doc) => {
    await act(async () => {
      root.render(
        <SourceConfigModal
          modalState="ACTIVE"
          setModalState={vi.fn()}
          document={document}
          onReingest={vi.fn()}
          onEnableGraphRAG={vi.fn()}
        />,
      );
    });
  };

  const readOnlyNotice = () =>
    document.body.textContent?.includes('common.viewOnlyNotice');

  const buttonLabels = () =>
    Array.from(document.body.querySelectorAll('button')).map(
      (b) => b.textContent,
    );

  it('a viewer with view_config only sees the read-only notice', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'viewer',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(true);
    const note = document.body.querySelector('[data-slot="alert"]');
    expect(note?.getAttribute('role')).toBe('note');
    // View-only: no Save, and Cancel becomes a lone Close.
    expect(buttonLabels()).not.toContain('settings.sources.configModal.save');
    expect(buttonLabels()).not.toContain('cancel');
    expect(buttonLabels()).toContain('common.close');
  });

  it('an editor can edit (no read-only notice)', async () => {
    await render(
      doc({
        access: 'editor',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: ['edit', 'use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(false);
    expect(buttonLabels()).toContain('settings.sources.configModal.save');
    expect(buttonLabels()).toContain('cancel');
  });

  it('follows allowed_actions over the legacy team_access', async () => {
    await render(
      doc({
        access: 'viewer',
        ownership: 'team',
        team_access: 'editor',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(readOnlyNotice()).toBe(true);
  });

  it('an owned source without access fields is editable', async () => {
    await render(doc({}));
    expect(readOnlyNotice()).toBe(false);
  });
});
