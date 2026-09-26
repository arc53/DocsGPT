import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SourcesPopoverFooter from './SourcesPopoverFooter';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

const renderFooter = async (onNavigate = vi.fn(), onUploadClick = vi.fn()) => {
  await act(async () =>
    root.render(
      <MemoryRouter>
        <SourcesPopoverFooter
          onNavigate={onNavigate}
          onUploadClick={onUploadClick}
        />
      </MemoryRouter>,
    ),
  );
  return { onNavigate, onUploadClick };
};

describe('SourcesPopoverFooter', () => {
  it('puts the link and Upload new in one row that wraps when it does not fit', async () => {
    await renderFooter();
    const row = container.firstElementChild as HTMLElement;
    const classes = row.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'flex',
        'flex-wrap',
        'items-center',
        'justify-between',
      ]),
    );
    expect(classes).not.toContain('flex-col');
  });

  it('renders the sources link as an inline link Button', async () => {
    await renderFooter();
    const link = container.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('/settings/sources');
    expect(link.dataset.slot).toBe('button');
    expect(link.className).toContain('text-primary');
    expect(link.className).toContain('text-sm');
  });

  it('fires onNavigate from the link and onUploadClick from the button', async () => {
    const { onNavigate, onUploadClick } = await renderFooter();
    await act(async () => container.querySelector('a')!.click());
    await act(async () => container.querySelector('button')!.click());
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(onUploadClick).toHaveBeenCalledOnce();
  });
});
