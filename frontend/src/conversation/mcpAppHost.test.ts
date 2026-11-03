import { describe, expect, it, vi } from 'vitest';

import {
  isOpenableLink,
  MCP_APPS_PROTOCOL_VERSION,
  McpAppError,
  McpAppHost,
  type McpAppHostOptions,
} from './mcpAppHost';

const ORIGIN = 'http://127.0.0.1:7091';

function setup(overrides: Partial<McpAppHostOptions> = {}) {
  const frame = { postMessage: vi.fn() } as unknown as Window;
  const options: McpAppHostOptions = {
    frame: () => frame,
    origin: ORIGIN,
    resource: {
      html: '<html>view</html>',
      csp: { connectDomains: ['https://esm.sh'] },
      permissions: { clipboardWrite: {} },
    },
    context: () => ({
      theme: 'dark',
      styles: { variables: {} },
      locale: 'en',
      timeZone: 'UTC',
      platform: 'web',
      displayMode: 'inline',
      availableDisplayModes: ['inline'],
      containerDimensions: { width: 600, maxHeight: 700 },
    }),
    callTool: vi.fn(async () => ({ content: [], isError: false })),
    openLink: vi.fn(),
    onSize: vi.fn(),
    onInitialized: vi.fn(),
    ...overrides,
  };
  const host = new McpAppHost(options);
  const posted = () =>
    (frame.postMessage as ReturnType<typeof vi.fn>).mock.calls.map(
      ([message, origin]) => ({ message, origin }),
    );
  const receive = (data: unknown, from: unknown = frame, origin = ORIGIN) =>
    host.handle({ data, source: from, origin } as MessageEvent);
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
  return { host, options, posted, receive, flush };
}

const initialize = (receive: (data: unknown) => void) => {
  receive({ jsonrpc: '2.0', id: 1, method: 'ui/initialize', params: {} });
  receive({ jsonrpc: '2.0', method: 'ui/notifications/initialized' });
};

describe('McpAppHost', () => {
  it('sends the view to the sandbox once it is ready', () => {
    const { posted, receive } = setup();
    receive({
      jsonrpc: '2.0',
      method: 'ui/notifications/sandbox-proxy-ready',
      params: {},
    });
    expect(posted()).toEqual([
      {
        message: {
          jsonrpc: '2.0',
          method: 'ui/notifications/sandbox-resource-ready',
          params: {
            html: '<html>view</html>',
            csp: { connectDomains: ['https://esm.sh'] },
            permissions: { clipboardWrite: {} },
          },
        },
        origin: ORIGIN,
      },
    ]);
  });

  it('ignores messages from other frames and origins', () => {
    const { posted, receive } = setup();
    const ready = {
      jsonrpc: '2.0',
      method: 'ui/notifications/sandbox-proxy-ready',
    };
    receive(ready, {}, ORIGIN);
    receive(ready, undefined, 'https://evil.example');
    expect(posted()).toEqual([]);
  });

  it('answers ui/initialize with the protocol, capabilities and context', async () => {
    const { posted, receive, flush } = setup();
    receive({ jsonrpc: '2.0', id: 7, method: 'ui/initialize', params: {} });
    await flush();
    const answer = posted()[0].message;
    expect(answer.id).toBe(7);
    expect(answer.result.protocolVersion).toBe(MCP_APPS_PROTOCOL_VERSION);
    expect(answer.result.hostInfo.name).toBe('DocsGPT');
    expect(answer.result.hostCapabilities.serverTools).toEqual({});
    expect(answer.result.hostCapabilities.sandbox.permissions).toEqual({
      clipboardWrite: {},
    });
    expect(answer.result.hostContext.theme).toBe('dark');
  });

  it('sends nothing to the view before it initialized', async () => {
    const { host, posted, receive, options, flush } = setup();
    host.sendToolInput({ elements: '[]' });
    expect(posted()).toEqual([]);

    initialize(receive);
    await flush();
    expect(options.onInitialized).toHaveBeenCalledTimes(1);
    host.sendToolInput({ elements: '[]' });
    host.sendToolResult({ content: [], structuredContent: { id: 'c' } });
    const methods = posted().map((p) => p.message.method);
    expect(methods).toContain('ui/notifications/tool-input');
    expect(methods).toContain('ui/notifications/tool-result');
  });

  it('proxies the view’s tool calls', async () => {
    const callTool = vi.fn(async () => ({
      content: [{ type: 'text', text: 'ok' }],
    }));
    const { posted, receive, flush } = setup({ callTool });
    receive({
      jsonrpc: '2.0',
      id: 'a',
      method: 'tools/call',
      params: { name: 'read_checkpoint', arguments: { id: 'c' } },
    });
    await flush();
    expect(callTool).toHaveBeenCalledWith('read_checkpoint', { id: 'c' });
    expect(posted()[0].message).toEqual({
      jsonrpc: '2.0',
      id: 'a',
      result: { content: [{ type: 'text', text: 'ok' }] },
    });
  });

  it('turns a refused call into a JSON-RPC error', async () => {
    const callTool = vi.fn(async () => {
      throw new McpAppError(-32000, 'The user declined');
    });
    const { posted, receive, flush } = setup({ callTool });
    receive({
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: { name: 'save_checkpoint' },
    });
    await flush();
    expect(posted()[0].message.error).toEqual({
      code: -32000,
      message: 'The user declined',
    });
  });

  it('opens only http(s) links', async () => {
    const { options, posted, receive, flush } = setup();
    receive({
      jsonrpc: '2.0',
      id: 3,
      method: 'ui/open-link',
      params: { url: 'javascript:alert(1)' },
    });
    receive({
      jsonrpc: '2.0',
      id: 4,
      method: 'ui/open-link',
      params: { url: 'https://excalidraw.com/#json=1' },
    });
    await flush();
    expect(options.openLink).toHaveBeenCalledTimes(1);
    expect(options.openLink).toHaveBeenCalledWith(
      'https://excalidraw.com/#json=1',
    );
    expect(posted()[0].message.error.code).toBe(-32602);
  });

  it('reports size changes', () => {
    const { options, receive } = setup();
    receive({
      jsonrpc: '2.0',
      method: 'ui/notifications/size-changed',
      params: { width: 500, height: 420 },
    });
    receive({
      jsonrpc: '2.0',
      method: 'ui/notifications/size-changed',
      params: { height: 'tall' },
    });
    expect(options.onSize).toHaveBeenCalledTimes(1);
    expect(options.onSize).toHaveBeenCalledWith(420);
  });

  it('answers unknown methods with method-not-found', async () => {
    const { posted, receive, flush } = setup();
    receive({ jsonrpc: '2.0', id: 9, method: 'ui/message', params: {} });
    await flush();
    expect(posted()[0].message.error.code).toBe(-32601);
  });

  it('asks the view before tearing it down', async () => {
    const { host, posted, receive, flush } = setup();
    initialize(receive);
    await flush();
    const done = host.teardown('closed');
    const request = posted().find(
      (p) => p.message.method === 'ui/resource-teardown',
    )!.message;
    receive({ jsonrpc: '2.0', id: request.id, result: {} });
    await expect(done).resolves.toBeUndefined();
  });
});

describe('isOpenableLink', () => {
  it.each([
    ['https://excalidraw.com', true],
    ['http://localhost:3000/x', true],
    ['javascript:alert(1)', false],
    ['data:text/html,hi', false],
    ['not a url', false],
    [42, false],
  ])('%s → %s', (url, expected) => {
    expect(isOpenableLink(url)).toBe(expected);
  });
});
