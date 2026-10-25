import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.formatted}` : key,
  }),
}));

const drive = vi.hoisted(() => ({
  openPicker: vi.fn(),
  pickerToken: vi.fn(),
  authRendered: vi.fn(),
}));
vi.mock('react-google-drive-picker', () => ({
  default: () => [drive.openPicker],
}));
vi.mock('../api/services/connectorsService', () => ({
  default: {
    pickerToken: (...args: unknown[]) => drive.pickerToken(...args),
    getCatalog: vi.fn().mockResolvedValue({ success: true, connectors: [] }),
    listConnections: vi
      .fn()
      .mockResolvedValue({ success: true, connections: [] }),
  },
}));
vi.mock('./ConnectorAuth', () => ({
  default: () => {
    drive.authRendered();
    return null;
  },
}));
vi.mock('@/env', () => ({
  envVar: (name: string) =>
    name === 'VITE_GOOGLE_CLIENT_ID' ? '123-abc.apps.example' : '',
}));

import connectorsReducer from '../connectors/connectorsSlice';
import GoogleDrivePicker from './GoogleDrivePicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('GoogleDrivePicker', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.values(drive).forEach((fn) => fn.mockReset());
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (props = {}) => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <GoogleDrivePicker
            token={null}
            connectionId="conn-1"
            onSelectionChange={() => undefined}
            {...props}
          />
        </Provider>,
      );
    });
  };

  const button = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    );

  it('lists what was picked as rows, with no sign-in block of its own', async () => {
    drive.pickerToken.mockResolvedValue({ success: true, access_token: 'at' });
    drive.openPicker.mockImplementation(({ callbackFunction }) =>
      callbackFunction({
        action: 'picked',
        docs: [
          {
            id: 'f1',
            name: 'Rate annex.xlsx',
            mimeType: 'application/vnd.ms-excel',
            sizeBytes: '2048',
          },
        ],
      }),
    );
    const onSelectionChange = vi.fn();
    await render({ onSelectionChange });
    expect(drive.authRendered).not.toHaveBeenCalled();
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    expect(onSelectionChange).toHaveBeenLastCalledWith(['f1'], []);
    const card = container.querySelector('[data-slot="card"]')!;
    expect(card.getAttribute('data-variant')).toBe('outline');
    expect(card.querySelector('[data-slot="list-row"]')?.textContent).toContain(
      'Rate annex.xlsx',
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('filePicker.itemsSelected:1');
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          'button[aria-label="modals.uploadDoc.connectors.googleDrive.removeItem"]',
        )!
        .click(),
    );
    expect(onSelectionChange).toHaveBeenLastCalledWith([], []);
  });

  it('offers Reconnect when the sign-in expired', async () => {
    drive.pickerToken.mockResolvedValue({ success: false });
    const onReconnect = vi.fn();
    await render({ onReconnect });
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    expect(drive.openPicker).not.toHaveBeenCalled();
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('settings.connectors.detail.expired');
    const reconnect = button('settings.connectors.status.reconnect')!;
    // A link in the Alert's sentence: its size and the Alert's colour.
    expect(reconnect.dataset.size).toBe('text');
    expect(reconnect.dataset.tone).toBe('current');
    await act(async () => reconnect.click());
    expect(onReconnect).toHaveBeenCalled();
  });

  it('lets folders and shared-drive items be picked', async () => {
    drive.pickerToken.mockResolvedValue({ success: true, access_token: 'at' });
    drive.openPicker.mockImplementation(({ callbackFunction }) =>
      callbackFunction({
        action: 'picked',
        docs: [
          {
            id: 'folder-1',
            name: 'Policies',
            mimeType: 'application/vnd.google-apps.folder',
          },
          { id: 'f1', name: 'a.pdf', mimeType: 'application/pdf' },
        ],
      }),
    );
    const onSelectionChange = vi.fn();
    await render({ onSelectionChange });
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    expect(drive.openPicker).toHaveBeenCalledWith(
      expect.objectContaining({
        setIncludeFolders: true,
        setSelectFolderEnabled: true,
        supportDrives: true,
      }),
    );
    // With a type filter set, Google's Select ignores a highlighted folder,
    // so folders are picked from an unfiltered view.
    expect(drive.openPicker.mock.calls[0][0].viewMimeTypes).toBeUndefined();
    expect(onSelectionChange).toHaveBeenLastCalledWith(['f1'], ['folder-1']);
    expect(container.textContent).toContain('filePicker.folder');
  });

  it('adds a shared drives tab once the Picker API is loaded', async () => {
    const calls: Array<[string, unknown]> = [];
    class DocsView {
      constructor(viewId: unknown) {
        calls.push(['viewId', viewId]);
      }
      setEnableDrives(on: boolean) {
        calls.push(['setEnableDrives', on]);
        return this;
      }
      setIncludeFolders(on: boolean) {
        calls.push(['setIncludeFolders', on]);
        return this;
      }
      setSelectFolderEnabled(on: boolean) {
        calls.push(['setSelectFolderEnabled', on]);
        return this;
      }
      setMimeTypes(types: string) {
        calls.push(['setMimeTypes', types.includes('application/pdf')]);
        return this;
      }
    }
    Object.assign(window, {
      google: { picker: { DocsView, ViewId: { DOCS: 'docs' } } },
    });
    try {
      drive.pickerToken.mockResolvedValue({
        success: true,
        access_token: 'at',
      });
      await render();
      await act(async () =>
        button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
      );
      const { customViews } = drive.openPicker.mock.calls[0][0];
      expect(customViews).toHaveLength(1);
      expect(customViews[0]).toBeInstanceOf(DocsView);
      expect(calls).toEqual([
        ['viewId', 'docs'],
        ['setEnableDrives', true],
        ['setIncludeFolders', true],
        ['setSelectFolderEnabled', true],
      ]);
    } finally {
      delete (window as { google?: unknown }).google;
    }
  });

  it("opens Google's picker with the server's client id", async () => {
    drive.pickerToken.mockResolvedValue({ success: true, access_token: 'at' });
    await render({ clientId: '999-server.apps.example' });
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    expect(drive.openPicker).toHaveBeenCalledWith(
      expect.objectContaining({
        clientId: '999-server.apps.example',
        appId: '999',
      }),
    );
  });

  it('picks files only when the server cannot read folders', async () => {
    drive.pickerToken.mockResolvedValue({
      success: true,
      access_token: 'at',
      folders: 'off',
    });
    await render();
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    expect(drive.openPicker).toHaveBeenCalledWith(
      expect.objectContaining({
        setIncludeFolders: true,
        setSelectFolderEnabled: false,
      }),
    );
    expect(drive.openPicker.mock.calls[0][0].viewMimeTypes).toContain(
      'application/pdf',
    );
    expect(container.textContent).toContain(
      'modals.uploadDoc.connectors.googleDrive.filesOnly',
    );
  });

  it('asks to share picked folders with the service account', async () => {
    drive.pickerToken.mockResolvedValue({
      success: true,
      access_token: 'at',
      folders: 'service_account',
      share_with: 'reader@project.iam.gserviceaccount.com',
    });
    drive.openPicker.mockImplementation(({ callbackFunction }) =>
      callbackFunction({
        action: 'picked',
        docs: [
          {
            id: 'folder-1',
            name: 'Policies',
            mimeType: 'application/vnd.google-apps.folder',
          },
        ],
      }),
    );
    await render();
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    const hint = container.querySelector('[data-variant="info"]')!;
    expect(hint.textContent).toContain(
      'modals.uploadDoc.connectors.googleDrive.shareFolders',
    );
    expect(hint.textContent).toContain(
      'reader@project.iam.gserviceaccount.com',
    );
  });

  it('opens without a shared drives tab before the Picker API loads', async () => {
    drive.pickerToken.mockResolvedValue({ success: true, access_token: 'at' });
    await render();
    await act(async () =>
      button('modals.uploadDoc.connectors.googleDrive.selectFiles')!.click(),
    );
    expect(drive.openPicker.mock.calls[0][0].customViews).toBeUndefined();
  });
});
