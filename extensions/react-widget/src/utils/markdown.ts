import MarkdownIt from 'markdown-it';
import { highlight } from './prism';

type Markdown = ReturnType<typeof MarkdownIt>;
type CoreRule = Parameters<Markdown['core']['ruler']['push']>[1];
type StateCore = Parameters<CoreRule>[0];
type Token = StateCore['tokens'][number];

/** What `renderAnswer` needs to know about the answer it renders. */
export type AnswerEnv = {
  /** How many sources the answer has; only `[1]`…`[sourceCount]` link. */
  sourceCount?: number;
};

const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

// Lucide Copy and Check at 16px, as markup for the code frame's button.
const SVG_ATTRS =
  'xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"';
const COPY_SVG = `<svg class="dgpt-code-copy-idle" ${SVG_ATTRS}><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>`;
const CHECK_SVG = `<svg class="dgpt-code-copy-done" ${SVG_ATTRS}><path d="M20 6 9 17l-5-5"></path></svg>`;

/**
 * Turns `[N]` in the answer's prose into source pills, the way the app's
 * `remarkCitations` does: plain text only (code and link text are other
 * tokens), a grouped `[1, 2]` gives one pill per number, numbers past the
 * answer's sources stay text, and a backslash-escaped `\[1\]` stays brackets.
 * Runs before `text_join`, while an escape is still its own token.
 */
const citations = (state: StateCore) => {
  const count = (state.env as AnswerEnv | undefined)?.sourceCount ?? 0;
  if (count <= 0) return;
  const citable = (n: number) => n >= 1 && n <= count;

  for (const block of state.tokens) {
    if (block.type !== 'inline' || !block.children) continue;
    const children: Token[] = [];
    let linkDepth = 0;

    for (const token of block.children) {
      if (token.type === 'link_open') linkDepth += 1;
      if (token.type === 'link_close') linkDepth -= 1;
      if (token.type !== 'text' || linkDepth > 0) {
        children.push(token);
        continue;
      }

      const text = token.content;
      let last = 0;
      for (const match of text.matchAll(CITATION)) {
        const numbers = match[1].split(',').map((n) => n.trim());
        if (!numbers.some((n) => citable(Number(n)))) continue;
        const start = match.index;
        if (start > last) {
          const before = new state.Token('text', '', 0);
          before.content = text.slice(last, start);
          children.push(before);
        }
        for (const n of numbers) {
          if (citable(Number(n))) {
            const cite = new state.Token('dgpt_cite', '', 0);
            cite.meta = { n };
            children.push(cite);
          } else {
            const plain = new state.Token('text', '', 0);
            plain.content = `[${n}]`;
            children.push(plain);
          }
        }
        last = start + match[0].length;
      }
      if (last === 0) {
        children.push(token);
        continue;
      }
      if (last < text.length) {
        const after = new state.Token('text', '', 0);
        after.content = text.slice(last);
        children.push(after);
      }
    }
    block.children = children;
  }
};

const createMarkdown = () => {
  // Bare URLs become links, as GFM autolinks do in the app: a scheme, a
  // `www.` host or an email. Other guessed domains stay text, or `main.py`
  // (Paraguay) and `config.io` would link. linkify-it knows only the older
  // and country TLDs, so the common newer ones are added for `www.` hosts.
  const md = new MarkdownIt({ linkify: true });
  md.linkify
    .set({ fuzzyLink: true })
    .tlds(
      ['app', 'blog', 'cloud', 'dev', 'online', 'site', 'tech', 'xyz'],
      true,
    );
  const matchLinks = md.linkify.match.bind(md.linkify);
  // markdown-it calls this only after `test` passed and expects an array.
  md.linkify.match = (text: string) =>
    (matchLinks(text) ?? []).filter(
      (link) => link.schema !== '' || /^www\./i.test(link.raw),
    );

  const escape = md.utils.escapeHtml;

  md.core.ruler.before('text_join', 'dgpt_citations', citations);
  md.renderer.rules.dgpt_cite = (tokens, idx) => {
    const n = escape(String((tokens[idx].meta as { n: string }).n));
    return `<button type="button" class="dgpt-cite" data-cite="${n}" aria-label="Open source ${n}">${n}</button>`;
  };

  md.renderer.rules.table_open = () =>
    '<div class="dgpt-table-container"><table class="dgpt-table">';
  md.renderer.rules.table_close = () => '</table></div>';

  // An answer link must not replace the host page and close the chat.
  const renderToken: NonNullable<typeof md.renderer.rules.link_open> = (
    tokens,
    idx,
    options,
    _env,
    self,
  ) => self.renderToken(tokens, idx, options);
  const linkOpen = md.renderer.rules.link_open ?? renderToken;
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    tokens[idx].attrSet('target', '_blank');
    tokens[idx].attrSet('rel', 'noopener noreferrer');
    return linkOpen(tokens, idx, options, env, self);
  };

  // The app's CodeFrame: a header with the language and a copy button over
  // the code, which keeps its lines and scrolls sideways.
  md.renderer.rules.fence = (tokens, idx) => {
    const token = tokens[idx];
    const language = token.info.trim().split(/\s+/)[0].toLowerCase();
    const code = token.content.replace(/\n$/, '');
    const body = (language ? highlight(code, language) : null) ?? escape(code);
    const label = language ? escape(language) : 'text';
    return (
      '<div class="dgpt-code">' +
      `<div class="dgpt-code-header"><span class="dgpt-code-language">${label}</span>` +
      `<button type="button" class="dgpt-code-copy" aria-label="Copy code">${COPY_SVG}${CHECK_SVG}</button></div>` +
      `<pre class="dgpt-code-body"><code>${body}</code></pre>` +
      '</div>'
    );
  };
  md.renderer.rules.code_block = md.renderer.rules.fence;

  return md;
};

const md = createMarkdown();

/** Renders an answer's markdown to HTML; sanitise the result before use. */
export const renderAnswer = (source: string, env: AnswerEnv = {}): string =>
  md.render(source, { ...env });
