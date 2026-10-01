import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockDispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'token',
  useDispatch: () => mockDispatch,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'name' in opts ? `${key}(${opts.name})` : key,
  }),
}));

// The browser itself is out of scope: render the row menu of one file and
// one folder, and the confirm FileTree hands it.
vi.mock('./tree/TreeBrowser', () => ({
  default: ({
    getRowMenuOptions,
    extraContent,
  }: {
    getRowMenuOptions: (ctx: {
      name: string;
      isFile: boolean;
      defaultViewOption: { label: string };
    }) => Array<{ label: string; onClick: () => void }>;
    extraContent: React.ReactNode;
  }) => (
    <div>
      {[
        { name: 'rates.pdf', isFile: true },
        { name: 'contracts', isFile: false },
      ].map((row) => (
        <div key={row.name} data-testid={`row-${row.name}`}>
          {getRowMenuOptions({
            ...row,
            defaultViewOption: { label: 'view' },
          })
            .filter((o) => o.label !== 'view')
            .map((o) => (
              <button key={o.label} type="button" onClick={o.onClick}>
                {o.label}
              </button>
            ))}
        </div>
      ))}
      {extraContent}
    </div>
  ),
}));

// Closes at once on a submit, like the real one for a sync-ish handler.
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: {
    modalState: string;
    handleSubmit: () => unknown;
    submitLabel: string;
  }) =>
    props.modalState === 'ACTIVE' ? (
      <button
        type="button"
        data-testid="confirm-submit"
        onClick={() => props.handleSubmit()}
      >
        {props.submitLabel}
      </button>
    ) : null,
}));

const waitForTerminal = vi.fn();
vi.mock('./tree/useReingestWait', () => ({
  useReingestSseWaiter: () => ({
    waitForTerminal: (...a: unknown[]) => waitForTerminal(...a),
    mountedRef: { current: true },
  }),
}));

const manageSourceFiles = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    manageSourceFiles: (...a: unknown[]) => manageSourceFiles(...a),
  },
}));

import FileTree from './FileTree';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const respond = (body: unknown) =>
  Promise.resolve({ json: () => Promise.resolve(body) });

const flush = async () => {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

describe('FileTree delete', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mockDispatch.mockReset();
    manageSourceFiles.mockReset();
    waitForTerminal.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const deleteRow = async (name: string) => {
    act(() => {
      root.render(
        <FileTree docId="s1" sourceName="Rates" onBackToDocuments={() => {}} />,
      );
    });
    const del = container.querySelector<HTMLButtonElement>(
      `[data-testid="row-${name}"] button`,
    )!;
    act(() => del.click());
    act(() =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="confirm-submit"]')!
        .click(),
    );
    await flush();
  };

  const toasts = () =>
    mockDispatch.mock.calls
      .map(([action]) => action as { payload?: Record<string, unknown> })
      .filter((a) => a?.payload?.variant === 'destructive')
      .map((a) => a.payload!.message);

  it('closes the confirm at once and queues the delete', async () => {
    manageSourceFiles.mockReturnValue(respond({ success: false }));
    await deleteRow('rates.pdf');
    expect(
      container.querySelector('[data-testid="confirm-submit"]'),
    ).toBeNull();
    expect(manageSourceFiles).toHaveBeenCalledTimes(1);
  });

  it('a refused file delete shows a destructive toast naming the file', async () => {
    manageSourceFiles.mockReturnValue(respond({ success: false }));
    await deleteRow('rates.pdf');
    expect(toasts()).toEqual(['settings.sources.deleteItemFailed(rates.pdf)']);
  });

  it('a failed folder delete request shows the toast naming the folder', async () => {
    manageSourceFiles.mockReturnValue(Promise.reject(new Error('down')));
    await deleteRow('contracts');
    expect(toasts()).toEqual(['settings.sources.deleteItemFailed(contracts)']);
  });

  it('a delete whose re-index fails shows the toast too', async () => {
    manageSourceFiles.mockReturnValue(
      respond({ success: true, reingest_task_id: 'r1', source_id: 's1' }),
    );
    waitForTerminal.mockResolvedValue('failed');
    await deleteRow('rates.pdf');
    expect(toasts()).toEqual(['settings.sources.deleteItemFailed(rates.pdf)']);
  });

  it('shows no toast when the delete and re-index complete', async () => {
    manageSourceFiles.mockReturnValue(
      respond({ success: true, reingest_task_id: 'r1', source_id: 's1' }),
    );
    waitForTerminal.mockResolvedValue('completed');
    await deleteRow('rates.pdf');
    expect(toasts()).toEqual([]);
  });
});
