import { defaultUrlTransform } from 'react-markdown';

/**
 * Dead-link handling for generated files.
 *
 * Nothing in DocsGPT ever asks a model to emit a ``sandbox:`` URL — the scheme
 * comes from the model's own pretraining (it is OpenAI Code Interpreter's path
 * convention). Models announce artifacts they create with one, in at least
 * seven shapes:
 *
 *   sandbox:/artifact/<uuid>      sandbox:/artifact/A1
 *   sandbox:/artifacts/<uuid>     sandbox:/mnt/data/<filename>
 *   sandbox:/tmp/<filename>       sandbox:/<filename>
 *   artifact:A1
 *
 * The same path also arrives with no scheme at all (``/mnt/data/report.pdf``,
 * ``report.pdf``) or as ``file:///mnt/data/report.pdf``. Those are the same
 * mistake wearing different clothes, so they resolve the same way — except that
 * an unresolvable scheme-less href stays an ordinary link, since a relative URL
 * is something a model may legitimately write.
 *
 * Left alone the result is worse than a no-op: react-markdown's
 * ``defaultUrlTransform`` blanks any unknown protocol, so the anchor renders as
 * ``href=""`` and clicking it opens the current page again in a new tab — which
 * reads to the user as "the download failed".
 *
 * The file itself is real and already reachable through the artifact chip, so
 * these two helpers point the link at the chip instead: keep the scheme through
 * the sanitizer (:func:`sandboxUrlTransform`), then resolve it against the
 * turn's artifacts at render time (:func:`resolveSandboxLink`). Anything that
 * cannot be resolved is rendered as plain text rather than as a dead link.
 */

/**
 * Schemes models invent for a file they produced. ``sandbox:`` comes from
 * OpenAI Code Interpreter's path convention; ``artifact:`` is this product's
 * own short ref (``artifact:A1``) leaking into prose. react-markdown blanks
 * both, so both have to be intercepted.
 */
export const GENERATED_FILE_SCHEMES = [
  'sandbox:',
  'artifact:',
  // Browsers refuse to navigate to `file:` from an https page, so a `file:`
  // href is dead whatever we do with it; routing it here at least turns it into
  // the chip or plain text instead of react-markdown's blank `href=""`.
  'file:',
] as const;

export type SandboxArtifact = {
  id: string;
  /** Filename when the tool reported one, else a tool label. */
  label?: string;
  /** Tool that produced it; the artifact viewer keys its preview off this. */
  toolName?: string;
  /**
   * The model-facing handle (``A1``). Stable per *conversation*, not per turn —
   * matching it positionally against one turn's artifacts opens the wrong file
   * as soon as an earlier turn produced any.
   */
  ref?: string;
};

export type SandboxLinkResolution =
  /** Not a sandbox URL — render the normal anchor. */
  | { kind: 'external' }
  /** Points at a real artifact on this turn — render the chip's open action. */
  | { kind: 'artifact'; artifact: SandboxArtifact }
  /** Sandbox URL with nothing behind it — render the label as plain text. */
  | { kind: 'plain' };

/**
 * URL sanitizer for ``ReactMarkdown`` that preserves the generated-file
 * schemes and defers everything else to react-markdown's own transform, so
 * `javascript:` and `data:` stay blocked.
 */
export function sandboxUrlTransform(url: string): string {
  if (matchedScheme(url)) return url;
  return defaultUrlTransform(url);
}

function matchedScheme(href: string | undefined | null): string | null {
  if (typeof href !== 'string') return null;
  // URL schemes are case-insensitive; `Sandbox:` must not slip through to the
  // anchor branch, where it would render the dead `href=""` link again.
  const lowered = href.toLowerCase();
  return (
    GENERATED_FILE_SCHEMES.find((scheme) => lowered.startsWith(scheme)) ?? null
  );
}

/** Short refs the artifact tool hands back, e.g. ``A1`` is the first artifact. */
const SHORT_REF = /^a(\d+)$/i;

/** Any URL scheme, so ``https:`` and ``mailto:`` are left alone. */
const ANY_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

/**
 * Last match wins. Within one turn the model's prose means the file as it
 * stands after the *last* write, so a rerun that overwrites ``report.pdf``
 * should open the new copy rather than the one it replaced.
 */
function findLast<T>(
  items: T[],
  predicate: (item: T) => boolean,
): T | undefined {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index])) return items[index];
  }
  return undefined;
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/**
 * Resolve a markdown href against the artifacts produced on the same turn.
 *
 * Args:
 *     href: The raw href from the markdown link, if any.
 *     artifacts: Artifacts this turn produced, in the order the tool made them
 *         (``A1`` is the first).
 *
 * Returns:
 *     How the link should be rendered. ``external`` for ordinary URLs,
 *     ``artifact`` when a target was found, ``plain`` for an unresolvable
 *     sandbox URL.
 */
export function resolveSandboxLink(
  href: string | undefined | null,
  artifacts: SandboxArtifact[] | undefined,
): SandboxLinkResolution {
  if (typeof href !== 'string' || !href) return { kind: 'external' };
  const scheme = matchedScheme(href);
  // A scheme-less href may be a genuine relative link or in-page anchor, so it
  // only ever *upgrades* to a chip on a hit and is otherwise left untouched.
  if (!scheme && (href.startsWith('#') || ANY_SCHEME.test(href))) {
    return { kind: 'external' };
  }
  const miss: SandboxLinkResolution = scheme
    ? { kind: 'plain' }
    : { kind: 'external' };

  const available = artifacts ?? [];
  // Strip the scheme, any leading slashes, and a trailing query/fragment.
  const path = href
    .slice(scheme?.length ?? 0)
    .replace(/^\/+/, '')
    .split(/[?#]/)[0];
  if (!path) return miss;

  const segments = path.split('/').filter(Boolean).map(decodeSegment);
  if (segments.length === 0) return miss;

  const last = segments[segments.length - 1];

  // Try every identifier the segment could be, in order of certainty. A ref is
  // matched against the artifact's own ``ref``, never by position: ``A2`` is the
  // conversation's second artifact, which on a later turn is not this turn's
  // second one.
  const byId = findLast(available, (artifact) => artifact.id === last);
  if (byId) return { kind: 'artifact', artifact: byId };

  if (SHORT_REF.test(last)) {
    const wanted = last.toUpperCase();
    const byRef = findLast(
      available,
      (artifact) => (artifact.ref ?? '').toUpperCase() === wanted,
    );
    if (byRef) return { kind: 'artifact', artifact: byRef };
  }

  // Fabricated paths (``/mnt/data/…``, ``/tmp/…``, a bare filename) — and
  // ``/artifact/<filename>``, which the model also writes — usually still name
  // a file that exists as an artifact on this turn.
  const byName = findLast(
    available,
    (artifact) =>
      !!artifact.label && artifact.label.toLowerCase() === last.toLowerCase(),
  );
  if (byName) return { kind: 'artifact', artifact: byName };

  return miss;
}
