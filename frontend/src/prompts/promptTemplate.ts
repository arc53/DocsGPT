/**
 * A client-side check of a template prompt's Jinja structure, so Save can
 * refuse a text that would fail at chat time (a review that accepted the
 * `{% if %}` change but not its `{% endif %}`). The save route doesn't parse
 * templates; the chat does, and a prompt that doesn't parse fails every
 * answer. It looks only for definite faults, so it never refuses a template
 * Jinja would take: a tag, variable or comment left open, and block tags
 * that don't pair up. Tags it doesn't know are left alone.
 */

// Tags that open a block closed by `end<name>`. `set` opens one only
// without `=` (`{% set x %}…{% endset %}`).
const BLOCKS = new Set([
  'if',
  'for',
  'macro',
  'call',
  'filter',
  'with',
  'block',
  'autoescape',
  'set',
]);
// Tags allowed only inside a block, and the blocks each may sit in.
const MIDDLE: Record<string, string[]> = {
  elif: ['if'],
  else: ['if', 'for'],
};

const OPENERS = /\{[{%#]/g;
const CLOSERS: Record<string, string> = { '{': '}}', '%': '%}', '#': '#}' };
const END_RAW = /\{%[-+]?\s*endraw\s*[-+]?%\}/g;

/**
 * Whether a template prompt won't parse. Only a template is checked: as
 * the chat does, a prompt is one when it holds both `{{` and `}}`.
 *
 * Args:
 *   content: The prompt's text.
 *
 * Returns:
 *   True when the template is sure to fail.
 */
export function templateBroken(content: string): boolean {
  if (!content.includes('{{') || !content.includes('}}')) return false;
  const open: string[] = [];
  OPENERS.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = OPENERS.exec(content)) !== null) {
    const kind = match[0][1];
    const close = content.indexOf(CLOSERS[kind], match.index + 2);
    if (close < 0) return true;
    OPENERS.lastIndex = close + 2;
    if (kind !== '%') continue;
    const words = content
      .slice(match.index + 2, close)
      .replace(/^[-+]/, '')
      .replace(/-$/, '')
      .trim()
      .split(/\s+/);
    const tag = words[0];
    if (tag === 'raw') {
      END_RAW.lastIndex = close + 2;
      const end = END_RAW.exec(content);
      if (!end) return true;
      OPENERS.lastIndex = end.index + end[0].length;
    } else if (BLOCKS.has(tag)) {
      if (tag !== 'set' || !words.join(' ').includes('=')) open.push(tag);
    } else if (tag in MIDDLE) {
      if (!MIDDLE[tag].includes(open[open.length - 1])) return true;
    } else if (tag.startsWith('end') && BLOCKS.has(tag.slice(3))) {
      if (open.pop() !== tag.slice(3)) return true;
    }
  }
  return open.length > 0;
}
