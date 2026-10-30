import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useDarkTheme: () => [false, () => undefined],
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import SourcesTrigger from './SourcesTrigger';
import ToolsTrigger from './ToolsTrigger';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// The four pickers share one chrome: a "Tools" or "Knowledge" title, a
// "Search …" field and the Go to … footer.
describe('chat picker chrome', () => {
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
    document.body.innerHTML = '';
  });

  const chrome = () => {
    const content = document.querySelector('[data-slot="popover-content"]')!;
    return {
      title: content.querySelector('h3')?.textContent,
      placeholder: content
        .querySelector('[data-slot="command-input"]')
        ?.getAttribute('placeholder'),
      footer: content.querySelector('[data-slot="multi-select-footer"]'),
    };
  };

  it('titles the tools picker Tools, with Go to Tools under the list', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <ToolsTrigger
            open
            onOpenChange={() => undefined}
            items={[]}
            selectedIds={[]}
            onToggle={() => undefined}
            loading={false}
            onAddTool={() => undefined}
          />
        </MemoryRouter>,
      );
    });
    const { title, placeholder, footer } = chrome();
    expect(title).toBe('settings.tools.label');
    expect(placeholder).toBe('settings.tools.searchPlaceholder');
    expect(footer?.querySelector('a')?.getAttribute('href')).toBe(
      '/settings/tools',
    );
  });

  it('titles the knowledge picker Knowledge, with Go to Knowledge under the list', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <SourcesTrigger
            open
            onOpenChange={() => undefined}
            items={[]}
            selectedIds={[]}
            onToggle={() => undefined}
            selectedDocs={null}
            onUploadClick={() => undefined}
          />
        </MemoryRouter>,
      );
    });
    const { title, placeholder, footer } = chrome();
    expect(title).toBe('conversation.sources.knowledge');
    expect(placeholder).toBe('agents.form.sourcePopup.searchPlaceholder');
    expect(footer?.querySelector('a')).not.toBeNull();
  });
});
