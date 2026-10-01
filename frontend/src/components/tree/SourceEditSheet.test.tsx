import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { TooltipProvider } from '../ui/tooltip';
import SourceEditSheet, { type SourceEditSheetProps } from './SourceEditSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SourceEditSheet', () => {
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

  const render = async (props: Partial<SourceEditSheetProps> = {}) => {
    const all: SourceEditSheetProps = {
      open: true,
      onClose: vi.fn(),
      title: 'Edit page',
      description: '/a.md · v1',
      value: '# Hello',
      onChange: vi.fn(),
      dirty: false,
      onSave: vi.fn(),
      saveLabel: 'Save',
      fieldLabel: 'Page content',
      ...props,
    };
    await act(async () => {
      root.render(
        <TooltipProvider>
          <SourceEditSheet {...all} />
        </TooltipProvider>,
      );
    });
    return all;
  };

  const button = (text: string) =>
    [...document.body.querySelectorAll('button')].find(
      (b) => b.textContent === text,
    ) as HTMLButtonElement | undefined;

  it('shows the draft in a labelled field and keeps Save off until it changes', async () => {
    await render();
    const field = document.body.querySelector('textarea');
    expect(field?.value).toBe('# Hello');
    expect(field?.getAttribute('aria-label')).toBe('Page content');
    expect(button('Save')?.disabled).toBe(true);
    await render({ dirty: true });
    expect(button('Save')?.disabled).toBe(false);
  });

  it('closes at once when nothing changed', async () => {
    const props = await render();
    await act(async () => button('settings.sources.editor.cancel')?.click());
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('asks before dropping unsaved edits', async () => {
    const props = await render({ dirty: true });
    await act(async () => button('settings.sources.editor.cancel')?.click());
    expect(props.onClose).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(
      'settings.sources.editor.discardMessage',
    );
    await act(async () => button('settings.sources.editor.discard')?.click());
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('renders the alert above the field', async () => {
    await render({ alert: <div role="alert">Conflict</div> });
    const alert = document.body.querySelector('[role="alert"]');
    const field = document.body.querySelector('textarea');
    expect(alert).not.toBeNull();
    expect(
      alert!.compareDocumentPosition(field!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('reopens on Write after the caller closed it from Preview', async () => {
    await render();
    const preview = [...document.body.querySelectorAll('[role="tab"]')].find(
      (b) => b.textContent === 'settings.sources.editor.preview',
    )!;
    await act(async () => {
      preview.dispatchEvent(
        new MouseEvent('mousedown', { bubbles: true, button: 0 }),
      );
    });
    expect(document.body.querySelector('textarea')).toBeNull();
    // A save: the caller closes the sheet itself, then opens it again.
    await render({ open: false });
    await render({ open: true });
    expect(document.body.querySelector('textarea')).not.toBeNull();
  });

  it('keeps the title and path in a fixed header with the X', async () => {
    const props = await render();
    const header = document.body.querySelector('[data-slot="panel-header"]')!;
    expect(header.querySelector('[data-slot="sheet-title"]')?.textContent).toBe(
      'Edit page',
    );
    const description = header.querySelector(
      '[data-slot="sheet-description"]',
    )!;
    expect(description.textContent).toBe('/a.md · v1');
    expect(description.querySelector('.font-mono')).not.toBeNull();
    expect(document.body.querySelectorAll('.overflow-y-auto')).toHaveLength(1);
    expect(document.body.querySelector('.pr-12')).toBeNull();
    await act(async () =>
      header
        .querySelector<HTMLButtonElement>('[aria-label="sidePanel.close"]')!
        .click(),
    );
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });
});
