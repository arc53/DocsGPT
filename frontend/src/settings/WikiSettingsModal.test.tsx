import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { service } = vi.hoisted(() => ({
  service: { getWikiSettings: vi.fn(), updateWikiSettings: vi.fn() },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('../api/services/userService', () => ({ default: service }));

import type { Doc } from '../models/misc';
import WikiSettingsModal from './WikiSettingsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const wiki: Doc = {
  id: 'wiki-1',
  name: 'Handbook',
  date: '',
  model: '',
  type: 'wiki',
  config: { kind: 'wiki' },
};

const reply = (status: number, body: unknown) =>
  Promise.resolve({ ok: status < 400, status, json: async () => body });

const OWNER = ['use', 'edit', 'manage_settings'];

describe('WikiSettingsModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async () => {
    await act(async () => {
      root.render(<WikiSettingsModal document={wiki} onClose={vi.fn()} />);
    });
  };

  const theSwitch = () =>
    document.body.querySelector<HTMLButtonElement>('[role="switch"]');

  it('shows the stored value, off by default', async () => {
    service.getWikiSettings.mockReturnValue(
      reply(200, { allow_outside_edits: false, allowed_actions: OWNER }),
    );
    await render();
    expect(service.getWikiSettings).toHaveBeenCalledWith('wiki-1', 'token');
    expect(document.body.textContent).toContain(
      'settings.sources.wiki.settings.outsideEdits.label',
    );
    expect(theSwitch()?.getAttribute('aria-checked')).toBe('false');
    expect(theSwitch()?.disabled).toBe(false);
  });

  it('the owner turns it on', async () => {
    service.getWikiSettings.mockReturnValue(
      reply(200, { allow_outside_edits: false, allowed_actions: OWNER }),
    );
    service.updateWikiSettings.mockReturnValue(
      reply(200, { allow_outside_edits: true, allowed_actions: OWNER }),
    );
    await render();
    await act(async () => theSwitch()!.click());
    expect(service.updateWikiSettings).toHaveBeenCalledWith(
      'wiki-1',
      { allow_outside_edits: true },
      'token',
    );
    expect(theSwitch()?.getAttribute('aria-checked')).toBe('true');
  });

  it('flips back and says so when the save fails', async () => {
    service.getWikiSettings.mockReturnValue(
      reply(200, { allow_outside_edits: false, allowed_actions: OWNER }),
    );
    service.updateWikiSettings.mockReturnValue(reply(403, { success: false }));
    await render();
    await act(async () => theSwitch()!.click());
    expect(theSwitch()?.getAttribute('aria-checked')).toBe('false');
    expect(document.body.textContent).toContain(
      'settings.sources.wiki.settings.saveError',
    );
  });

  it('is read-only without manage_settings', async () => {
    service.getWikiSettings.mockReturnValue(
      reply(200, { allow_outside_edits: true, allowed_actions: ['use'] }),
    );
    await render();
    expect(theSwitch()?.getAttribute('aria-checked')).toBe('true');
    expect(theSwitch()?.disabled).toBe(true);
    expect(document.body.textContent).toContain('common.viewOnlyNotice');
  });

  it('says when the settings could not load', async () => {
    service.getWikiSettings.mockReturnValue(reply(500, { success: false }));
    await render();
    expect(theSwitch()).toBeNull();
    expect(document.body.textContent).toContain(
      'settings.sources.wiki.settings.loadError',
    );
  });
});
