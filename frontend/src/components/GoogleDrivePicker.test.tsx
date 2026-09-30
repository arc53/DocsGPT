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
});
