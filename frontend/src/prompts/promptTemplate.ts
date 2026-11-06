/**
 * A client-side check of a template prompt's Jinja structure, so Save can
 * refuse a text that would fail at chat time (a review that accepted the
 * `{% if %}` change but not its `{% endif %}`). The save route doesn't parse
 * templates; the chat does, and a prompt that doesn't parse fails every
 * answer. It looks only for definite faults, so it never refuses a template
 * Jinja would take: a tag, variable or comment left open (or a quoted
 * string inside one), and block tags that don't pair up. Tags it doesn't
 * know are left alone.
 */

// Tags that open a block closed by `end<name>`. `set` opens one unless it
// assigns: an `=` before any filter (`{% set x = a | f(b=1) %}`) assigns,
// while `{% set x %}` and `{% set x | f(w=80) %}` open a block.
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
// Tags allowed only inside a block, and the blocks each may sit in. A Map,
// so a tag named like an object property (`constructor`) isn't found here.
const MIDDLE = new Map<string, string[]>([
  ['elif', ['if']],
  ['else', ['if', 'for']],
]);

const OPENERS = /\{[{%#]/g;
const CLOSERS = new Map([
  ['{', '}}'],
  ['%', '%}'],
  ['#', '#}'],
]);
const BRACKETS = new Map([
  ['(', ')'],
  ['[', ']'],
  ['{', '}'],
]);
const CLOSING_BRACKETS = new Set(BRACKETS.values());
// A tag's name, as Jinja reads it: it ends at the first character that
// can't be in a name, so `if(x)` and `endif+` are `if` and `endif`.
const TAG_NAME = /^[A-Za-z_][A-Za-z0-9_]*/;
const END_RAW = /\{%[-+]?\s*endraw\s*[-+]?%\}/g;

/**
 * Where the variable or tag opened at `from` ends, as Jinja's lexer reads
 * it: a quoted string ('…' or "…", with backslash escapes) and an open
 * bracket hold any delimiter inside them. A comment has no strings.
 *
 * Args:
 *   content: The prompt's text.
 *   from: The index just past the opener.
 *   kind: The opener's second character: `{`, `%` or `#`.
 *
 * Returns:
 *   The closer's index, or -1 when it never closes.
 */
function closerOf(content: string, from: number, kind: string): number {
  const closer = CLOSERS.get(kind) ?? '';
  if (kind === '#') return content.indexOf(closer, from);
  let depth = 0;
  for (let i = from; i < content.length; i++) {
    const char = content[i];
    if (depth === 0 && content.startsWith(closer, i)) return i;
    if (char === '"' || char === "'") {
      // Past the string; one that never ends fails in Jinja too.
      let end = i + 1;
      while (end < content.length && content[end] !== char)
        end += content[end] === '\\' ? 2 : 1;
      if (end >= content.length) return -1;
      i = end;
    } else if (BRACKETS.has(char)) depth++;
    // A stray closing bracket fails in Jinja; not counting it never refuses.
    else if (CLOSING_BRACKETS.has(char) && depth > 0) depth--;
  }
  return -1;
}

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
    const close = closerOf(content, match.index + 2, kind);
    if (close < 0) return true;
    OPENERS.lastIndex = close + 2;
    if (kind !== '%') continue;
    const body = content
      .slice(match.index + 2, close)
      .replace(/^[-+]/, '')
      .replace(/[-+]$/, '')
      .trim();
    const tag = TAG_NAME.exec(body)?.[0] ?? '';
    const middle = MIDDLE.get(tag);
    if (tag === 'raw') {
      END_RAW.lastIndex = close + 2;
      const end = END_RAW.exec(content);
      if (!end) return true;
      OPENERS.lastIndex = end.index + end[0].length;
    } else if (BLOCKS.has(tag)) {
      if (tag !== 'set' || !/^[^=|]*=/.test(body)) open.push(tag);
    } else if (middle) {
      if (!middle.includes(open[open.length - 1])) return true;
    } else if (tag.startsWith('end') && BLOCKS.has(tag.slice(3))) {
      if (open.pop() !== tag.slice(3)) return true;
    }
  }
  return open.length > 0;
}
