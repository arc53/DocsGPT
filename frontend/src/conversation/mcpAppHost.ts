import type {
  McpAppResource,
  McpCallToolResult,
} from '../api/services/mcpAppsService';

/**
 * The chat's side of an MCP App view (SEP-1865, `io.modelcontextprotocol/ui`):
 * JSON-RPC over `postMessage` with the sandbox page, which relays to and from
 * the view in its inner frame. Phase 1 of the stable 2026-01-26 spec: the
 * handshake, the call's input and result, size changes, theme and locale,
 * links, the view's own tool calls, and teardown.
 * https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
 */
export const MCP_APPS_PROTOCOL_VERSION = '2026-01-26';

const METHOD_NOT_FOUND = -32601;
const INVALID_PARAMS = -32602;
const HOST_ERROR = -32000;
const TEARDOWN_WAIT_MS = 500;

type JsonRpcId = string | number;

type JsonRpcMessage = {
  jsonrpc: '2.0';
  id?: JsonRpcId;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: { code: number; message: string };
};

/** A JSON-RPC error answer to the view. */
export class McpAppError extends Error {
  constructor(
    public code: number,
    message: string,
  ) {
    super(message);
  }
}

export type McpAppHostContext = {
  theme: 'light' | 'dark';
  styles: { variables: Record<string, string> };
  locale: string;
  timeZone: string;
  platform: 'web';
  displayMode: 'inline';
  availableDisplayModes: ['inline'];
  containerDimensions: { width: number; maxHeight: number };
};

export type McpAppHostOptions = {
  /** The sandbox frame's window. */
  frame: () => Window | null;
  /** The sandbox page's origin; nothing else is listened to or posted to. */
  origin: string;
  resource: Pick<McpAppResource, 'html' | 'csp' | 'permissions'>;
  context: () => McpAppHostContext;
  callTool: (
    name: string,
    args: Record<string, unknown>,
  ) => Promise<McpCallToolResult>;
  openLink: (url: string) => void;
  onSize: (height: number) => void;
  onInitialized: () => void;
};

/** Spec style variables, each from the theme token it reads (`src/index.css`). */
const STYLE_TOKENS: Record<string, string> = {
  '--color-background-primary': '--background',
  '--color-background-secondary': '--muted',
  '--color-background-tertiary': '--accent',
  '--color-background-inverse': '--foreground',
  '--color-background-danger': '--destructive',
  '--color-text-primary': '--foreground',
  '--color-text-secondary': '--muted-foreground',
  '--color-text-tertiary': '--muted-foreground',
  '--color-text-inverse': '--background',
  '--color-text-danger': '--destructive',
  '--color-text-success': '--success',
  '--color-text-warning': '--warning',
  '--color-text-info': '--info',
  '--color-border-primary': '--border',
  '--color-border-secondary': '--border',
  '--color-ring-primary': '--ring',
  '--font-sans': '--font-sans',
  '--font-mono': '--font-mono',
  '--border-radius-md': '--radius',
};

/** The theme's tokens as the spec's style variables, resolved for the current theme. */
export function hostStyleVariables(
  root: Element = document.documentElement,
): Record<string, string> {
  const computed = getComputedStyle(root);
  const variables: Record<string, string> = {};
  for (const [variable, token] of Object.entries(STYLE_TOKENS)) {
    const value = computed.getPropertyValue(token).trim();
    if (value) variables[variable] = value;
  }
  return variables;
}

/** Whether `url` is one the chat opens for a view: http(s) only. */
export function isOpenableLink(url: unknown): url is string {
  if (typeof url !== 'string') return false;
  try {
    const { protocol } = new URL(url);
    return protocol === 'https:' || protocol === 'http:';
  } catch {
    return false;
  }
}

export class McpAppHost {
  private initialized = false;
  private nextId = 1;
  private waiting = new Map<JsonRpcId, () => void>();

  constructor(private options: McpAppHostOptions) {}

  /** Handle one `message` event; anything not from the sandbox frame is ignored. */
  handle(event: MessageEvent): void {
    if (
      event.source !== this.options.frame() ||
      event.origin !== this.options.origin
    )
      return;
    const message = event.data as JsonRpcMessage;
    if (!message || message.jsonrpc !== '2.0') return;
    if (message.method === undefined) {
      if (message.id !== undefined) {
        this.waiting.get(message.id)?.();
        this.waiting.delete(message.id);
      }
      return;
    }
    if (message.id !== undefined) void this.answer(message);
    else this.notified(message.method, message.params ?? {});
  }

  /** The call's arguments; the view gets them once, after it initialized. */
  sendToolInput(args: Record<string, unknown>): void {
    this.notify('ui/notifications/tool-input', { arguments: args });
  }

  sendToolResult(result: McpCallToolResult): void {
    this.notify('ui/notifications/tool-result', result);
  }

  sendToolCancelled(reason: string): void {
    this.notify('ui/notifications/tool-cancelled', { reason });
  }

  sendContext(context: Partial<McpAppHostContext>): void {
    this.notify('ui/notifications/host-context-changed', context);
  }

  /** Tell the view it is going away; resolves on its answer, or after a short wait. */
  teardown(reason: string): Promise<void> {
    if (!this.initialized) return Promise.resolve();
    const id = `teardown-${this.nextId++}`;
    return new Promise((resolve) => {
      const done = () => {
        this.waiting.delete(id);
        resolve();
      };
      this.waiting.set(id, done);
      this.post({
        jsonrpc: '2.0',
        id,
        method: 'ui/resource-teardown',
        params: { reason },
      });
      setTimeout(done, TEARDOWN_WAIT_MS);
    });
  }

  private notify(method: string, params: unknown): void {
    // Nothing reaches the view before its initialized notification (spec).
    if (!this.initialized) return;
    this.post({
      jsonrpc: '2.0',
      method,
      params: params as Record<string, unknown>,
    });
  }

  private post(message: JsonRpcMessage): void {
    this.options.frame()?.postMessage(message, this.options.origin);
  }

  private notified(method: string, params: Record<string, unknown>): void {
    if (method === 'ui/notifications/sandbox-proxy-ready') {
      const { html, csp, permissions } = this.options.resource;
      this.post({
        jsonrpc: '2.0',
        method: 'ui/notifications/sandbox-resource-ready',
        params: { html, csp, permissions },
      });
    } else if (method === 'ui/notifications/initialized') {
      if (this.initialized) return;
      this.initialized = true;
      this.options.onInitialized();
    } else if (method === 'ui/notifications/size-changed') {
      const height = params.height;
      if (typeof height === 'number' && Number.isFinite(height) && height > 0)
        this.options.onSize(height);
    }
  }

  private async answer(message: JsonRpcMessage): Promise<void> {
    const id = message.id as JsonRpcId;
    try {
      const result = await this.respond(
        message.method as string,
        message.params ?? {},
      );
      this.post({ jsonrpc: '2.0', id, result });
    } catch (error) {
      const code = error instanceof McpAppError ? error.code : HOST_ERROR;
      const text = error instanceof Error ? error.message : String(error);
      this.post({ jsonrpc: '2.0', id, error: { code, message: text } });
    }
  }

  private async respond(
    method: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    switch (method) {
      case 'ui/initialize': {
        const { csp, permissions } = this.options.resource;
        return {
          protocolVersion: MCP_APPS_PROTOCOL_VERSION,
          hostInfo: { name: 'DocsGPT', version: '1.0.0' },
          hostCapabilities: {
            openLinks: {},
            serverTools: {},
            logging: {},
            sandbox: { csp: csp ?? {}, permissions: permissions ?? {} },
          },
          hostContext: this.options.context(),
        };
      }
      case 'ping':
        return {};
      case 'tools/call': {
        if (typeof params.name !== 'string')
          throw new McpAppError(INVALID_PARAMS, 'A tool name is required');
        const args =
          params.arguments && typeof params.arguments === 'object'
            ? (params.arguments as Record<string, unknown>)
            : {};
        return this.options.callTool(params.name, args);
      }
      case 'ui/open-link':
        if (!isOpenableLink(params.url))
          throw new McpAppError(INVALID_PARAMS, 'Invalid URL');
        this.options.openLink(params.url);
        return {};
      // Phase 2: fullscreen, chat messages and model context.
      case 'ui/request-display-mode':
        return { mode: 'inline' };
      case 'ui/update-model-context':
        return {};
      default:
        throw new McpAppError(METHOD_NOT_FOUND, `${method} is not supported`);
    }
  }
}
