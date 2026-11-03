// @vitest-environment-options { "settings": { "disableIframePageLoading": true } }
import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    i18n: { language: 'en' },
    t: (key: string) => key,
  }),
}));

const readMcpAppView = vi.fn();
vi.mock('../api/services/mcpAppsService', () => ({
  readMcpAppView: (...args: unknown[]) => readMcpAppView(...args),
  callMcpAppTool: vi.fn(),
}));

import { TooltipProvider } from '../components/ui/tooltip';
import McpAppView from './McpAppView';
import type { ToolCallsType } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const call: ToolCallsType = {
  tool_name: 'mcp_tool',
  action_name: 'create_view',
  call_id: 'c1',
  arguments: { elements: '[]' },
  status: 'completed',
  ui: {
    resource_uri: 'ui://excalidraw/mcp-app.html',
    tool_id: 'row-1',
    result: { content: [], structuredContent: { checkpointId: 'x' } },
  },
};

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
  readMcpAppView.mockReset();
});

const render = async () => {
  const store = configureStore({
    reducer: { preference: () => ({ token: 'tok' }) },
  });
  await act(async () => {
    root.render(
      <Provider store={store}>
        <TooltipProvider>
          <McpAppView toolCall={call} fallback={<div>FALLBACK_CHIP</div>} />
        </TooltipProvider>
      </Provider>,
    );
  });
  await act(async () => {});
};

describe('McpAppView', () => {
  it('reads the view through the call’s tool row', async () => {
    readMcpAppView.mockResolvedValue(null);
    await render();
    expect(readMcpAppView).toHaveBeenCalledWith(
      'row-1',
      'ui://excalidraw/mcp-app.html',
      'tok',
      expect.any(AbortSignal),
    );
  });

  it('falls back to the ordinary step when MCP Apps are off', async () => {
    readMcpAppView.mockResolvedValue(null);
    await render();
    expect(container.textContent).toContain('FALLBACK_CHIP');
    expect(container.querySelector('iframe')).toBeNull();
  });

  it('falls back when the sandbox is on the app’s own origin', async () => {
    readMcpAppView.mockResolvedValue({
      html: '<html>',
      sandbox_url: `${window.location.origin}/api/mcp_apps/sandbox`,
    });
    await render();
    expect(container.textContent).toContain('FALLBACK_CHIP');
  });

  it('loads the sandbox page with the view’s CSP and permissions', async () => {
    readMcpAppView.mockResolvedValue({
      html: '<html>',
      csp: { connectDomains: ['https://esm.sh'] },
      permissions: { clipboardWrite: {} },
      sandbox_url: 'http://127.0.0.1:7091/api/mcp_apps/sandbox',
    });
    await render();
    const frame = container.querySelector('iframe')!;
    expect(frame).not.toBeNull();
    const src = new URL(frame.getAttribute('src')!);
    expect(src.origin).toBe('http://127.0.0.1:7091');
    expect(JSON.parse(src.searchParams.get('csp')!)).toEqual({
      connectDomains: ['https://esm.sh'],
    });
    expect(frame.getAttribute('sandbox')).toBe(
      'allow-scripts allow-same-origin allow-forms',
    );
    expect(frame.getAttribute('allow')).toBe('clipboard-write');
    expect(container.textContent).not.toContain('FALLBACK_CHIP');
  });

  it('shows a retryable error when the view fails to load', async () => {
    readMcpAppView.mockRejectedValue(new Error('502'));
    await render();
    expect(container.textContent).toContain('conversation.mcpApp.failedTitle');
  });

  it('gives up on a view that never arrives and frees its request', async () => {
    vi.useFakeTimers();
    try {
      let signal: AbortSignal | undefined;
      readMcpAppView.mockImplementation(
        (_id: string, _uri: string, _token: string, s: AbortSignal) => {
          signal = s;
          return new Promise(() => {});
        },
      );
      await render();
      expect(container.textContent).not.toContain(
        'conversation.mcpApp.failedTitle',
      );
      await act(async () => {
        vi.advanceTimersByTime(20_000);
      });
      expect(container.textContent).toContain(
        'conversation.mcpApp.failedTitle',
      );
      expect(signal?.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
