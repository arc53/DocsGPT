/**
 * Runs before `prismjs` loads (see `prism.ts`): keeps the host page's own
 * `window.Prism`, if any, and marks the copy about to load as manual so it
 * never highlights the host's code blocks.
 *
 * The stand-in inherits from the host's Prism. When the host's bundle has
 * already run `prismjs`, the bundler hands the widget that same instance and
 * the core does not run again, so the grammars register through the
 * stand-in onto the host's `languages`, `hooks` and `util`, not onto an
 * empty object.
 */
type PrismScope = { Prism?: unknown };

const scope: PrismScope | undefined =
  typeof window !== 'undefined' ? (window as unknown as PrismScope) : undefined;

const hostPrism = scope?.Prism;
const hadHostPrism = scope ? 'Prism' in scope : false;

const prototype =
  typeof hostPrism === 'object' || typeof hostPrism === 'function'
    ? hostPrism
    : null;

if (scope)
  scope.Prism = Object.assign(Object.create(prototype), { manual: true });

/** Puts the host's `window.Prism` back, or removes the widget's copy. */
export const restoreHostPrism = () => {
  if (!scope) return;
  if (hadHostPrism) scope.Prism = hostPrism;
  else delete scope.Prism;
};
