import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const { dispatch, service, state, deleted } = vi.hoisted(() => ({
  deleted: { result: undefined as void | Promise<unknown> },
  dispatch: vi.fn(),
  service: { deletePath: vi.fn() },
  state: {
    preference: {
      token: null,
      sourceDocs: [
        { id: 'a', name: 'A' },
        { id: 'b', name: 'B' },
      ],
      paginatedDocuments: [{ id: 'b', name: 'B' }],
    },
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useDispatch: () => dispatch,
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
}));

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('../api/services/userService', () => ({ default: service }));
vi.mock('../navigation/SectionShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../navigation/SectionIndexPage', () => ({ default: () => null }));
vi.mock('./Analytics', () => ({ default: () => null }));
vi.mock('./CustomModels', () => ({ default: () => null }));
vi.mock('./General', () => ({ default: () => null }));
vi.mock('./Logs', () => ({ default: () => null }));
vi.mock('./PersonalAccessTokens', () => ({ default: () => null }));
vi.mock('./Tools', () => ({ default: () => null }));
// Sources: one button that deletes the only listed source.
vi.mock('./Sources', () => ({
  default: ({
    paginatedDocuments,
    handleDeleteDocument,
  }: {
    paginatedDocuments: { id: string; name: string }[];
    handleDeleteDocument: (
      index: number,
      doc: unknown,
    ) => void | Promise<unknown>;
  }) => (
    <button
      type="button"
      onClick={() => {
        const result = handleDeleteDocument(0, paginatedDocuments[0]);
        // Mark it handled; the tests assert on it afterwards.
        if (result) result.catch(() => undefined);
        deleted.result = result;
      }}
    >
      DELETE
    </button>
  ),
}));

import Settings from './index';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Settings source delete', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    dispatch.mockReset();
    service.deletePath.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const clickDelete = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/settings/sources']}>
          <Routes>
            <Route path="/settings/*" element={<Settings />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    await act(async () => container.querySelector('button')!.click());
  };

  const actionTypes = () => dispatch.mock.calls.map(([a]) => a?.type);

  // The delete returns its promise to Sources' ConfirmationModal: a
  // failure rejects with the message the dialog shows, no toast.
  it('a forbidden delete rejects with the forbidden message and keeps the source', async () => {
    service.deletePath.mockResolvedValue({ ok: false, status: 403 });
    await clickDelete();
    expect(service.deletePath).toHaveBeenCalledWith('b', null);
    await expect(deleted.result).rejects.toThrow(
      'settings.sources.errors.forbidden',
    );
    expect(actionTypes()).not.toContain('actionToast/showActionToast');
    expect(actionTypes()).not.toContain('preference/setSourceDocs');
  });

  it('a failed request rejects with the delete message', async () => {
    service.deletePath.mockRejectedValue(new Error('network'));
    await clickDelete();
    await expect(deleted.result).rejects.toThrow(
      'settings.sources.errors.delete',
    );
    expect(actionTypes()).not.toContain('actionToast/showActionToast');
  });

  it('a successful delete drops the source by id from both lists', async () => {
    service.deletePath.mockResolvedValue({ ok: true, status: 200 });
    await clickDelete();
    await expect(deleted.result).resolves.toBeUndefined();
    expect(dispatch).toHaveBeenCalledWith({
      type: 'preference/setPaginatedDocuments',
      payload: [],
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: 'preference/setSourceDocs',
      payload: [{ id: 'a', name: 'A' }],
    });
  });
});
