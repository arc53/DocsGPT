/**
 * Runs before `prismjs` loads (see `prism.ts`): keeps the host page's own
 * `window.Prism`, if any, and marks the copy about to load as manual so it
 * never highlights the host's code blocks.
 */
type PrismScope = { Prism?: unknown };

const scope: PrismScope | undefined =
  typeof window !== 'undefined' ? (window as unknown as PrismScope) : undefined;

const hostPrism = scope?.Prism;
const hadHostPrism = scope ? 'Prism' in scope : false;

if (scope) scope.Prism = { manual: true };

/** Puts the host's `window.Prism` back, or removes the widget's copy. */
export const restoreHostPrism = () => {
  if (!scope) return;
  if (hadHostPrism) scope.Prism = hostPrism;
  else delete scope.Prism;
};
