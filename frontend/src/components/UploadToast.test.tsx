import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import uploadReducer, {
  addUploadTask,
  type UploadTask,
} from '../upload/uploadSlice';
import UploadToast from './UploadToast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () => configureStore({ reducer: { upload: uploadReducer } });

const task = (over: Partial<UploadTask>): UploadTask => ({
  id: 't1',
  fileName: 'a.pdf',
  progress: 40,
  status: 'training',
  ...over,
});

describe('UploadToast', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    localStorage.clear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <UploadToast />
        </Provider>,
      );
    });
  };

  it('renders nothing without tasks', async () => {
    await render();
    expect(container.innerHTML).toBe('');
  });

  it('renders one card of rows with no rail of its own', async () => {
    store.dispatch(
      addUploadTask(task({ id: 't1', fileName: 'a.pdf', stage: 'embedding' })),
    );
    store.dispatch(
      addUploadTask(task({ id: 't2', fileName: 'b.md', status: 'completed' })),
    );
    await render();
    expect(container.querySelectorAll('[data-slot="toast"]')).toHaveLength(1);
    expect(container.querySelector('[data-slot="toast-viewport"]')).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(container.querySelector('.fixed')).toBeNull();
    const rows = container.querySelectorAll('[data-slot="toast-item"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('b.md');
    expect(rows[0].querySelector('[data-status="success"]')).not.toBeNull();
    expect(rows[1].textContent).toContain(
      'modals.uploadDoc.progress.embedding',
    );
    expect(rows[1].querySelector('[role="progressbar"]')).not.toBeNull();
    expect(
      container.querySelector('[data-slot="toast-title"]')?.textContent,
    ).toBe('modals.uploadDoc.progress.upload');
  });

  it('tints the header and explains a failure', async () => {
    store.dispatch(
      addUploadTask(task({ status: 'failed', errorMessage: 'Too big' })),
    );
    await render();
    expect(
      container
        .querySelector('[data-slot="toast-header"]')
        ?.getAttribute('data-variant'),
    ).toBe('destructive');
    const row = container.querySelector('[data-slot="toast-item"]');
    expect(row?.querySelector('[data-status="destructive"]')).not.toBeNull();
    const message = container.querySelector('[data-slot="toast-message"]');
    expect(message?.textContent).toBe('Too big');
    expect(message?.className).toContain('text-destructive');
  });

  it('collapses the rows and dismisses every task', async () => {
    store.dispatch(addUploadTask(task({})));
    await render();
    const collapse = container.querySelector(
      'button[aria-label="modals.uploadDoc.progress.collapseDetails"]',
    ) as HTMLButtonElement;
    await act(async () => collapse.click());
    expect(
      container.querySelector(
        'button[aria-label="modals.uploadDoc.progress.expandDetails"]',
      ),
    ).not.toBeNull();
    const close = container.querySelector(
      'button[aria-label="modals.uploadDoc.progress.dismiss"]',
    ) as HTMLButtonElement;
    await act(async () => close.click());
    expect(container.innerHTML).toBe('');
  });
});
