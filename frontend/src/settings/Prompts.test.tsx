import React from 'react';
import { act } from 'react';
import { createRoot, Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Prompts from './Prompts';

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const getSinglePromptMock = vi.hoisted(() => vi.fn());

vi.mock('react-redux', () => ({
  useSelector: () => 'test-token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) =>
      options?.name ? `${key} ${options.name}` : key,
  }),
}));

vi.mock('react-router-dom', () => ({
  Link: ({
    to,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('../api/services/userService', () => ({
  default: {
    createPrompt: vi.fn(),
    deletePrompt: vi.fn(),
    getSinglePrompt: getSinglePromptMock,
    getUserTools: vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({ success: true, tools: [] }),
      }),
    ),
    updatePrompt: vi.fn(),
  },
}));

const prompts = [
  { id: 'default', name: 'Default', type: 'public' },
  { id: 'custom', name: 'Custom', type: 'private' },
];

let container: HTMLDivElement;
let root: Root;

const renderPrompts = (selectedPrompt = prompts[1]) => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);

  act(() => {
    root.render(
      <Prompts
        prompts={prompts}
        selectedPrompt={selectedPrompt}
        onSelectPrompt={vi.fn()}
        setPrompts={vi.fn()}
      />,
    );
  });
};

describe('Prompts', () => {
  beforeEach(() => {
    getSinglePromptMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ content: 'Saved custom prompt' }),
    });
  });

  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    container?.remove();
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('lets users edit the selected private prompt without opening the dropdown', async () => {
    renderPrompts(prompts[1]);

    const editButton = container.querySelector<HTMLButtonElement>(
      '[aria-label="Edit selected prompt"]',
    );

    expect(editButton).not.toBeNull();

    await act(async () => {
      editButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(getSinglePromptMock).toHaveBeenCalledWith('custom', 'test-token');
    expect(document.body.textContent).toContain('modals.prompts.editPrompt');
  });

  it('does not show direct editing for public prompts', () => {
    renderPrompts(prompts[0]);

    expect(
      container.querySelector('[aria-label="Edit selected prompt"]'),
    ).toBeNull();
  });
});
