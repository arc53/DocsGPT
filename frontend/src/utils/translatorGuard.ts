/**
 * Keep page translators from crashing React commits.
 *
 * Chrome Translate and similar extensions replace text nodes with <font>
 * wrappers. When React later removes such a node, or inserts next to it, it
 * calls `removeChild` / `insertBefore` on a parent that no longer holds the
 * node, the browser throws `NotFoundError`, and the nearest error boundary
 * swaps its whole subtree for the fallback (facebook/react#11538).
 *
 * The guard makes those two calls no-ops in exactly the case where the
 * browser would throw. The translated text stays as the translator left it;
 * React's next render of that spot fixes it or the translator rewrites it.
 */

let installed = false;

/**
 * Patch `Node.prototype.removeChild` and `insertBefore` to skip the moves a
 * page translator made impossible instead of throwing.
 *
 * Install before `createRoot`. Every other call goes to the native method
 * unchanged. Installing again while installed does nothing.
 *
 * Args:
 *   warn: receives one message per install the first time a call is skipped,
 *     so the case stays visible without flooding the console.
 *
 * Returns:
 *   A function that restores the native methods.
 */
export function installTranslatorGuard(
  warn: (message: string) => void = console.warn,
): () => void {
  if (installed || typeof Node === 'undefined') return () => undefined;
  installed = true;

  const proto = Node.prototype;
  const { removeChild, insertBefore } = proto;
  let warned = false;
  const report = (method: string) => {
    if (warned) return;
    warned = true;
    warn(
      `Skipped ${method}: the node is no longer where React left it, ` +
        'most likely moved by a page translator (facebook/react#11538). ' +
        'Later skips are not logged.',
    );
  };

  proto.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) {
      report('removeChild');
      return child;
    }
    return removeChild.call(this, child) as T;
  };
  proto.insertBefore = function <T extends Node>(
    this: Node,
    node: T,
    child: Node | null,
  ): T {
    if (child && child.parentNode !== this) {
      report('insertBefore');
      return node;
    }
    return insertBefore.call(this, node, child) as T;
  };

  let active = true;
  return () => {
    if (!active) return;
    active = false;
    proto.removeChild = removeChild;
    proto.insertBefore = insertBefore;
    installed = false;
  };
}
