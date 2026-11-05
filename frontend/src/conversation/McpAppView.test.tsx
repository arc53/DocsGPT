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
const readMcpAppResult = vi.fn();
const callMcpAppTool = vi.fn();
vi.mock('../api/services/mcpAppsService', () => ({
  readMcpAppView: (...args: unknown[]) => readMcpAppView(...args),
  readMcpAppResult: (...args: unknown[]) => readMcpAppResult(...args),
  callMcpAppTool: (...args: unknown[]) => callMcpAppTool(...args),
}));

// The host the view builds, with what it sent; the protocol is mcpAppHost.test's.
type HostOptions = {
  onInitialized: () => void;
  callTool: (name: string, args: Record<string, unknown>) => Promise<unknown>;
};
type FakeHost = {
  options: HostOptions;
  sendToolInput: ReturnType<typeof vi.fn>;
  sendToolResult: ReturnType<typeof vi.fn>;
  sendToolCancelled: ReturnType<typeof vi.fn>;
};
const hosts: FakeHost[] = [];
vi.mock('./mcpAppHost', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./mcpAppHost')>();
  class McpAppHost {
    sendToolInput = vi.fn();
    sendToolResult = vi.fn();
    sendToolCancelled = vi.fn();
    sendContext = vi.fn();
    handle = vi.fn();
    teardown = vi.fn(async () => {});
    constructor(public options: HostOptions) {
      hosts.push(this as unknown as FakeHost);
    }
  }
  return { ...actual, McpAppHost };
});

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
  readMcpAppResult.mockReset();
  callMcpAppTool.mockReset();
  hosts.length = 0;
});

const VIEW = {
  html: '<html>',
  sandbox_url: 'http://127.0.0.1:7091/api/mcp_apps/sandbox',
};

/** The call as a saved message keeps it: where its view is, no result. */
const saved: ToolCallsType = {
  ...call,
  ui: { resource_uri: 'ui://excalidraw/mcp-app.html', tool_id: 'row-1' },
};

const render = async (toolCall = call, messageId?: string) => {
  const store = configureStore({
    reducer: { preference: () => ({ token: 'tok' }) },
  });
  await act(async () => {
    root.render(
      <Provider store={store}>
        <TooltipProvider>
          <McpAppView
            toolCall={toolCall}
            messageId={messageId}
            fallback={<div>FALLBACK_CHIP</div>}
          />
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

  it('hands the view its inline result without reading it back', async () => {
    readMcpAppView.mockResolvedValue(VIEW);
    await render(call, 'm1');
    act(() => hosts[0].options.onInitialized());
    expect(readMcpAppResult).not.toHaveBeenCalled();
    expect(hosts[0].sendToolInput).toHaveBeenCalledWith({ elements: '[]' });
    expect(hosts[0].sendToolResult).toHaveBeenCalledWith(call.ui?.result);
  });

  it('reads a saved call’s result back and hands it to the view', async () => {
    const result = { content: [], structuredContent: { checkpointId: 'y' } };
    readMcpAppView.mockResolvedValue(VIEW);
    readMcpAppResult.mockResolvedValue(result);
    await render(saved, 'm1');
    expect(readMcpAppResult).toHaveBeenCalledWith(
      'm1',
      'c1',
      'tok',
      expect.any(AbortSignal),
    );
    act(() => hosts[0].options.onInitialized());
    expect(hosts[0].sendToolInput).toHaveBeenCalled();
    expect(hosts[0].sendToolResult).toHaveBeenCalledWith(result);
  });

  it('tells the view when a saved result is gone', async () => {
    readMcpAppView.mockResolvedValue(VIEW);
    readMcpAppResult.mockResolvedValue(null);
    await render(saved, 'm1');
    act(() => hosts[0].options.onInitialized());
    expect(hosts[0].sendToolResult).not.toHaveBeenCalled();
    expect(hosts[0].sendToolCancelled).toHaveBeenCalledWith(
      'conversation.mcpApp.resultUnavailable',
    );
  });

  it('shows what a view call would send before asking to allow it', async () => {
    readMcpAppView.mockResolvedValue(VIEW);
    callMcpAppTool.mockResolvedValue({ kind: 'needs_approval' });
    await render();
    let call: Promise<unknown> | undefined;
    act(() => {
      call = hosts[0].options.callTool('save_checkpoint', { id: 'board-7' });
      call.catch(() => {});
    });
    await act(async () => {});
    expect(container.textContent).toContain('conversation.mcpApp.approvalAsk');
    expect(container.textContent).toContain(
      'conversation.toolApproval.state.approval',
    );
    // A one-line preview beside the title, the whole of them behind Details.
    expect(container.textContent).toContain('{"id":"board-7"}');
    expect(container.querySelector('pre')).toBeNull();
    const details = container.querySelector<HTMLButtonElement>(
      'button[aria-expanded]',
    );
    await act(async () => details?.click());
    expect(container.querySelector('pre')?.textContent).toContain(
      '"id": "board-7"',
    );
    const deny = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'conversation.mcpApp.deny',
    );
    await act(async () => deny?.click());
    await expect(call).rejects.toThrow('declined');
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
