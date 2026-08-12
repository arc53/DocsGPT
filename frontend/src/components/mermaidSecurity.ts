import mermaid, { type RenderResult } from 'mermaid';

export type MermaidSecurityLevel = 'strict' | 'sandbox';

type MermaidRenderOptions = {
  id: string;
  code: string;
  isDarkTheme: boolean;
  securityLevel: MermaidSecurityLevel;
};

// Mermaid's own render queue does not snapshot its process-global config.
// Keep initialization and its matching render in one application-level task.
let renderQueue: Promise<void> = Promise.resolve();

/** Configure Mermaid immediately before one queued render. */
export function initializeSecureMermaid(
  isDarkTheme: boolean,
  securityLevel: MermaidSecurityLevel = 'strict',
): void {
  mermaid.initialize({
    startOnLoad: false,
    theme: isDarkTheme ? 'dark' : 'default',
    securityLevel,
    suppressErrorRendering: true,
  });
}

/** Render untrusted Mermaid source with configuration isolated from other views. */
export function renderMermaidDiagram({
  id,
  code,
  isDarkTheme,
  securityLevel,
}: MermaidRenderOptions): Promise<RenderResult> {
  const render = () => {
    initializeSecureMermaid(isDarkTheme, securityLevel);
    return mermaid.render(id, code);
  };
  const result = renderQueue.then(render, render);
  renderQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}
