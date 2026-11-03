import { RotateCw } from 'lucide-react';
import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import {
  callMcpAppTool,
  type McpAppResource,
  readMcpAppView,
} from '../api/services/mcpAppsService';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { IconButton } from '../components/ui/icon-button';
import { LoadingState } from '../components/ui/loading-state';
import { selectToken } from '../preferences/preferenceSlice';
import { getToolChipLabel } from '../utils/streamingStatusUtils';
import {
  hostStyleVariables,
  McpAppError,
  McpAppHost,
  type McpAppHostContext,
} from './mcpAppHost';
import { StepIcon } from './StepGroup';
import ToolCallCard from './ToolCallCard';
import { ToolCallsType } from './types';
import { cn } from '@/lib/utils';

/** The view's height until it reports its own. */
const DEFAULT_HEIGHT = 360;
/** The tallest a view grows inline, in px; the frame is also capped at 70svh. */
const MAX_HEIGHT = 1200;
/** A view that has not initialized by then failed to load. */
const LOAD_TIMEOUT_MS = 20_000;
// What the outer (sandbox) frame may do. The page it loads gives the inner
// frame the same, on the sandbox origin, never the app's.
const SANDBOX = 'allow-scripts allow-same-origin allow-forms';
const PERMISSIONS: Record<string, string> = {
  camera: 'camera',
  microphone: 'microphone',
  geolocation: 'geolocation',
  clipboardWrite: 'clipboard-write',
};

type Phase = 'loading' | 'ready' | 'failed' | 'unavailable';

type PendingApproval = { name: string; decide: (allowed: boolean) => void };

const isDark = () => document.documentElement.classList.contains('dark');

function allowAttribute(resource: McpAppResource): string | undefined {
  const asked = resource.permissions ?? {};
  const features = Object.keys(PERMISSIONS)
    .filter((key) => key in asked)
    .map((key) => PERMISSIONS[key]);
  return features.length ? features.join('; ') : undefined;
}

function sandboxSrc(resource: McpAppResource): string {
  const url = new URL(resource.sandbox_url as string);
  url.searchParams.set('csp', JSON.stringify(resource.csp ?? {}));
  return url.toString();
}

/**
 * An MCP tool call's interactive view (MCP Apps), inline in the answer: the
 * Excalidraw canvas `create_view` draws, for one. The view runs in the sandbox
 * page on its own origin and talks to the chat through `McpAppHost`; its own
 * tool calls go through `/api/mcp_apps/call` and ask first when the tool needs
 * approval. When MCP Apps are off, `fallback` (the ordinary step) shows.
 */
export default function McpAppView({
  toolCall,
  fallback,
}: {
  toolCall: ToolCallsType;
  fallback: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const token = useSelector(selectToken);
  const ui = toolCall.ui;
  const frameRef = useRef<HTMLIFrameElement>(null);
  const hostRef = useRef<McpAppHost | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [resource, setResource] = useState<McpAppResource | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const [approval, setApproval] = useState<PendingApproval | null>(null);

  // Read by the host's callbacks, which outlive the render that made them.
  const latest = useRef({ toolCall, token, language: i18n.language, t });
  latest.current = { toolCall, token, language: i18n.language, t };
  const toolId = ui?.tool_id;
  const resourceUri = ui?.resource_uri;

  useEffect(() => {
    if (!toolId || !resourceUri) return;
    let cancelled = false;
    const controller = new AbortController();
    // A read that never answers would spin for good and hold one of the
    // browser's few connections to the API.
    const timeout = window.setTimeout(() => {
      controller.abort();
      if (!cancelled) setPhase('failed');
    }, LOAD_TIMEOUT_MS);
    setPhase('loading');
    setResource(null);
    readMcpAppView(toolId, resourceUri, latest.current.token, controller.signal)
      .then((view) => {
        window.clearTimeout(timeout);
        if (cancelled) return;
        const sandbox = view?.sandbox_url ? new URL(view.sandbox_url) : null;
        // A sandbox on the app's own origin would run the view where the session lives.
        if (!view || !sandbox || sandbox.origin === window.location.origin) {
          setPhase('unavailable');
          return;
        }
        setResource(view);
      })
      .catch(() => {
        window.clearTimeout(timeout);
        if (!cancelled) setPhase('failed');
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [toolId, resourceUri, attempt]);

  const context = useCallback(
    (): McpAppHostContext => ({
      theme: isDark() ? 'dark' : 'light',
      styles: { variables: hostStyleVariables() },
      locale: latest.current.language,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      platform: 'web',
      displayMode: 'inline',
      availableDisplayModes: ['inline'],
      containerDimensions: {
        width: frameRef.current?.clientWidth ?? 0,
        maxHeight: MAX_HEIGHT,
      },
    }),
    [],
  );

  const askApproval = useCallback(
    (name: string) =>
      new Promise<boolean>((resolve) => {
        setApproval((current) => {
          // One question at a time: a second call while one waits is declined.
          if (current) {
            resolve(false);
            return current;
          }
          return {
            name,
            decide: (allowed) => {
              setApproval(null);
              resolve(allowed);
            },
          };
        });
      }),
    [],
  );

  // Built once per loaded view: the call is read through ``latest``, since a
  // streamed update replaces the call object and must not restart the view.
  useEffect(() => {
    if (!resource || !toolId) return;
    const origin = new URL(resource.sandbox_url as string).origin;
    const host = new McpAppHost({
      frame: () => frameRef.current?.contentWindow ?? null,
      origin,
      resource,
      context,
      callTool: async (name, args) => {
        const { token: current } = latest.current;
        let outcome = await callMcpAppTool(toolId, name, args, current);
        if (outcome.kind === 'needs_approval') {
          if (!(await askApproval(name)))
            throw new McpAppError(-32000, 'The user declined this tool call');
          outcome = await callMcpAppTool(toolId, name, args, current, true);
        }
        if (outcome.kind !== 'result')
          throw new McpAppError(
            -32000,
            outcome.kind === 'refused' ? outcome.error : 'Not approved',
          );
        return outcome.result;
      },
      openLink: (url) => {
        window.open(url, '_blank', 'noopener,noreferrer');
      },
      onSize: (next) => setHeight(Math.min(Math.ceil(next), MAX_HEIGHT)),
      onInitialized: () => {
        const call = latest.current.toolCall;
        setPhase('ready');
        host.sendToolInput(call.arguments ?? {});
        if (call.ui?.result) host.sendToolResult(call.ui.result);
        else if (call.status === 'error')
          host.sendToolCancelled(
            latest.current.t('conversation.mcpApp.callFailed'),
          );
      },
    });
    hostRef.current = host;
    const listener = (event: MessageEvent) => host.handle(event);
    window.addEventListener('message', listener);

    const timeout = window.setTimeout(() => {
      setPhase((current) => (current === 'ready' ? current : 'failed'));
    }, LOAD_TIMEOUT_MS);

    // The theme is a class on <html>; the view follows it.
    const observer = new MutationObserver(() =>
      host.sendContext({
        theme: isDark() ? 'dark' : 'light',
        styles: { variables: hostStyleVariables() },
      }),
    );
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => {
      window.clearTimeout(timeout);
      observer.disconnect();
      void host.teardown('closed');
      window.removeEventListener('message', listener);
      hostRef.current = null;
    };
  }, [resource, toolId, context, askApproval]);

  useEffect(() => {
    hostRef.current?.sendContext({ locale: i18n.language });
  }, [i18n.language]);

  if (!ui || phase === 'unavailable') return <>{fallback}</>;

  const reload = () => {
    approval?.decide(false);
    setHeight(DEFAULT_HEIGHT);
    setAttempt((n) => n + 1);
  };
  const label = getToolChipLabel(toolCall, t);

  return (
    // Stretched to the column (see BackgroundJobCard) so it never spills on a phone.
    <div className="w-full min-w-0" data-testid="mcp-app-view">
      <div className="animate-in fade-in my-2 mr-5 ml-6 min-w-0 duration-200 motion-reduce:animate-none">
        <ToolCallCard
          icon={<StepIcon call={toolCall} />}
          title={label}
          state={
            <Badge
              variant={
                phase === 'failed'
                  ? 'destructive'
                  : phase === 'ready'
                    ? 'success'
                    : 'neutral'
              }
            >
              {t(`conversation.mcpApp.state.${phase}`)}
            </Badge>
          }
          actions={
            approval ? (
              <>
                <Button
                  size="xs"
                  shape="pill"
                  onClick={() => approval.decide(true)}
                >
                  {t('conversation.mcpApp.allow')}
                </Button>
                <Button
                  size="xs"
                  shape="pill"
                  variant="outline"
                  onClick={() => approval.decide(false)}
                >
                  {t('conversation.mcpApp.deny')}
                </Button>
              </>
            ) : null
          }
          meta={
            <span className="flex justify-end">
              <IconButton
                variant="ghost"
                size="icon-xs"
                icon={RotateCw}
                label={t('conversation.mcpApp.reload')}
                onClick={reload}
              />
            </span>
          }
        >
          {approval && (
            <p className="mb-2">
              {t('conversation.mcpApp.approvalAsk', {
                tool: approval.name,
                interpolation: { escapeValue: false },
              })}
            </p>
          )}
          {phase === 'failed' ? (
            <EmptyState
              size="xs"
              illustration="none"
              tone="destructive"
              title={t('conversation.mcpApp.failedTitle')}
              description={t('conversation.mcpApp.failedDescription')}
              onRetry={reload}
            />
          ) : (
            <div className="relative min-w-0">
              {phase === 'loading' && (
                <LoadingState
                  fill="parent"
                  size="sm"
                  label={t('conversation.mcpApp.loading')}
                  className="absolute inset-0"
                />
              )}
              {resource && (
                <iframe
                  key={attempt}
                  ref={frameRef}
                  src={sandboxSrc(resource)}
                  sandbox={SANDBOX}
                  allow={allowAttribute(resource)}
                  title={t('conversation.mcpApp.frameTitle', {
                    name: label,
                    interpolation: { escapeValue: false },
                  })}
                  className={cn(
                    'block h-(--mcp-app-height) max-h-[70svh] w-full border-0',
                    resource.prefersBorder && 'border-border rounded-xl border',
                    phase !== 'ready' && 'opacity-0',
                  )}
                  style={{ '--mcp-app-height': `${height}px` } as CSSProperties}
                />
              )}
              {!resource && (
                <div
                  className="h-(--mcp-app-height)"
                  style={
                    {
                      '--mcp-app-height': `${DEFAULT_HEIGHT}px`,
                    } as CSSProperties
                  }
                />
              )}
            </div>
          )}
        </ToolCallCard>
      </div>
    </div>
  );
}
