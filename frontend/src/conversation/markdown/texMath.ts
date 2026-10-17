/**
 * LaTeX's own math delimiters, ``\( … \)`` and ``\[ … \]``, as micromark
 * constructs. Models write math this way far more often than with dollars, and
 * remark-math only knows dollars.
 *
 * The constructs emit the same tokens as `micromark-extension-math`, so
 * `remark-math`'s `mathFromMarkdown` turns them into ordinary `inlineMath` and
 * `math` nodes and rehype-katex renders them. `remark-math` has to run too.
 *
 * - Text: ``\(x\)`` and ``\[x\]`` anywhere in a paragraph become inline math.
 *   The span may wrap lines but not cross a paragraph; ``\\`` pairs are opaque
 *   (a LaTeX line break), a nested ``\( … \)`` of the same kind is kept whole,
 *   and whitespace-only content is not math, so an escaped task box
 *   ``- \[ \] todo`` stays text. ``\[`` right after a letter or digit is an
 *   escaped index (``arr\[0\]``), not math.
 * - Flow: a ``\[`` that starts a line opens display math, closed by a ``\]``
 *   that ends a line (the same line or a later one). Its lines are not parsed
 *   as markdown, so a lone ``=`` is not a setext underline. If a ``\]`` is
 *   followed by more text on its line, or the block is never closed, it is not
 *   a display block, and the text construct gets the ``\[`` instead: one line
 *   such as ``\[a\] and more`` must not swallow the rest of the answer.
 *
 * Written for this app rather than aliasing `micromark-extension-llm-math`
 * over `micromark-extension-math`, whose flow construct does exactly that
 * swallowing. Its structure follows that package and `micromark-extension-math`
 * (both MIT).
 */
import {
  asciiAlphanumeric,
  markdownLineEnding,
  markdownSpace,
} from 'micromark-util-character';
import { codes, types } from 'micromark-util-symbol';
import type {
  Code,
  Construct,
  Effects,
  Extension,
  State,
  TokenizeContext,
} from 'micromark-util-types';
import type { Processor } from 'unified';

import { addMicromarkExtension } from './micromarkExtension';

function tokenizeTexText(
  this: TokenizeContext,
  effects: Effects,
  ok: State,
  nok: State,
): State {
  // What precedes the opening backslash, read before it is consumed.
  const before = this.previous;
  let open: Code = null;
  let close: Code = null;
  let depth = 0;
  let hasContent = false;

  const closing: Construct = { tokenize: tokenizeClosing, partial: true };

  return start;

  function start(code: Code): State | undefined {
    effects.enter('mathText');
    effects.enter('mathTextSequence');
    effects.consume(code);
    return sequenceOpen;
  }

  function sequenceOpen(code: Code): State | undefined {
    if (code === codes.leftParenthesis) {
      close = codes.rightParenthesis;
    } else if (code === codes.leftSquareBracket && !asciiAlphanumeric(before)) {
      close = codes.rightSquareBracket;
    } else {
      return nok(code);
    }
    open = code;
    effects.consume(code);
    effects.exit('mathTextSequence');
    return between;
  }

  function between(code: Code): State | undefined {
    if (code === codes.eof) return nok(code);
    if (code === codes.backslash) {
      return effects.check(closing, closeSequence, escape)(code);
    }
    // A line ending is kept as data: TeX reads it as a space, and dropping it
    // would fuse ``\alpha`` with the next line's first letter.
    if (markdownLineEnding(code)) {
      effects.enter('mathTextData');
      effects.consume(code);
      effects.exit('mathTextData');
      return between;
    }
    effects.enter('mathTextData');
    return data(code);
  }

  function data(code: Code): State | undefined {
    if (
      code === codes.eof ||
      code === codes.backslash ||
      markdownLineEnding(code)
    ) {
      effects.exit('mathTextData');
      return between(code);
    }
    if (!markdownSpace(code)) hasContent = true;
    effects.consume(code);
    return data;
  }

  function escape(code: Code): State | undefined {
    effects.enter('mathTextData');
    effects.consume(code);
    hasContent = true;
    return escaped;
  }

  function escaped(code: Code): State | undefined {
    if (code === codes.eof || markdownLineEnding(code)) {
      effects.exit('mathTextData');
      return between(code);
    }
    if (code === open) depth++;
    // Only reached for a nested close: the outermost one is `closing`.
    if (code === close) depth--;
    effects.consume(code);
    return data;
  }

  function closeSequence(code: Code): State | undefined {
    if (!hasContent) return nok(code);
    effects.enter('mathTextSequence');
    effects.consume(code);
    return closeBracket;
  }

  function closeBracket(code: Code): State | undefined {
    effects.consume(code);
    return done;
  }

  function done(code: Code): State | undefined {
    effects.exit('mathTextSequence');
    effects.exit('mathText');
    return ok(code);
  }

  function tokenizeClosing(effects: Effects, ok: State, nok: State): State {
    return (code) => {
      effects.enter('mathTextSequence');
      effects.consume(code);
      return (next) => {
        if (next !== close || depth !== 0) return nok(next);
        effects.exit('mathTextSequence');
        return ok(next);
      };
    };
  }
}

/** A ``\(`` or ``\[`` opens math unless its backslash is itself escaped. */
function previousTex(this: TokenizeContext, code: Code): boolean {
  return (
    code !== codes.backslash ||
    this.events[this.events.length - 1][1].type === types.characterEscape
  );
}

const texText: Construct = {
  name: 'mathTexText',
  tokenize: tokenizeTexText,
  previous: previousTex,
};

function tokenizeTexFlow(
  this: TokenizeContext,
  effects: Effects,
  ok: State,
  nok: State,
): State {
  // Set while micromark asks whether the block may interrupt a paragraph.
  const interrupt = this.interrupt;
  // Whether the line being entered is a lazy continuation.
  const lazyLine = () => this.parser.lazy[this.now().line];
  const tail = this.events[this.events.length - 1];
  // The fence's own indent, stripped from the lines inside it too.
  const initialSize =
    tail && tail[1].type === types.linePrefix
      ? tail[2].sliceSerialize(tail[1], true).length
      : 0;

  const closingFence: Construct = {
    tokenize: tokenizeClosingFence,
    partial: true,
  };
  const nonLazyLine: Construct = {
    tokenize: tokenizeNonLazyLine,
    partial: true,
  };

  return start;

  function start(code: Code): State | undefined {
    effects.enter('mathFlow');
    effects.enter('mathFlowFence');
    effects.enter('mathFlowFenceSequence');
    effects.consume(code);
    return sequenceOpen;
  }

  function sequenceOpen(code: Code): State | undefined {
    if (code !== codes.leftSquareBracket) return nok(code);
    effects.consume(code);
    effects.exit('mathFlowFenceSequence');
    return fenceWhitespace;
  }

  function fenceWhitespace(code: Code): State | undefined {
    if (!markdownSpace(code)) return fenceEnd(code);
    effects.enter(types.whitespace);
    return fenceWhitespaceInside(code);
  }

  function fenceWhitespaceInside(code: Code): State | undefined {
    if (markdownSpace(code)) {
      effects.consume(code);
      return fenceWhitespaceInside;
    }
    effects.exit(types.whitespace);
    return fenceEnd(code);
  }

  function fenceEnd(code: Code): State | undefined {
    effects.exit('mathFlowFence');
    return lineContent(code);
  }

  // Anywhere in a line of the block, outside a value chunk.
  function lineContent(code: Code): State | undefined {
    if (code === codes.eof) return nok(code);
    if (markdownLineEnding(code)) {
      // To interrupt a paragraph only the opening line has to hold up.
      if (interrupt) return ok(code);
      return effects.attempt(nonLazyLine, lineStart, nok)(code);
    }
    if (code === codes.backslash) {
      return effects.check(
        { tokenize: tokenizeBracketClose, partial: true },
        atClose,
        valueEscape,
      )(code);
    }
    effects.enter('mathFlowValue');
    return value(code);
  }

  function lineStart(code: Code): State | undefined {
    if (initialSize === 0 || !markdownSpace(code)) return lineContent(code);
    effects.enter(types.linePrefix);
    return linePrefix(code, 0);
  }

  function linePrefix(code: Code, size: number): State | undefined {
    if (markdownSpace(code) && size < initialSize) {
      effects.consume(code);
      return (next: Code) => linePrefix(next, size + 1);
    }
    effects.exit(types.linePrefix);
    return lineContent(code);
  }

  function value(code: Code): State | undefined {
    if (
      code === codes.eof ||
      code === codes.backslash ||
      markdownLineEnding(code)
    ) {
      effects.exit('mathFlowValue');
      return lineContent(code);
    }
    effects.consume(code);
    return value;
  }

  // A ``\]`` closes the block only when the rest of its line is blank; with
  // anything after it, this is a line of prose, not a display block.
  function atClose(code: Code): State | undefined {
    return effects.attempt(closingFence, after, nok)(code);
  }

  function after(code: Code): State | undefined {
    effects.exit('mathFlow');
    return ok(code);
  }

  // ``\\`` and ``\x`` pairs are content, so ``\\]`` is not a close.
  function valueEscape(code: Code): State | undefined {
    effects.enter('mathFlowValue');
    effects.consume(code);
    return valueEscaped;
  }

  function valueEscaped(code: Code): State | undefined {
    if (code === codes.eof || markdownLineEnding(code)) {
      effects.exit('mathFlowValue');
      return lineContent(code);
    }
    effects.consume(code);
    return value;
  }

  function tokenizeBracketClose(
    effects: Effects,
    ok: State,
    nok: State,
  ): State {
    return (code) => {
      effects.enter('mathFlowFenceSequence');
      effects.consume(code);
      return (next) => {
        if (next !== codes.rightSquareBracket) return nok(next);
        effects.exit('mathFlowFenceSequence');
        return ok(next);
      };
    };
  }

  function tokenizeClosingFence(
    effects: Effects,
    ok: State,
    nok: State,
  ): State {
    return (code) => {
      effects.enter('mathFlowFence');
      effects.enter('mathFlowFenceSequence');
      effects.consume(code);
      return (bracket) => {
        effects.consume(bracket);
        effects.exit('mathFlowFenceSequence');
        return afterSequence;
      };
    };

    function afterSequence(code: Code): State | undefined {
      if (markdownSpace(code)) {
        effects.enter(types.whitespace);
        return trailing(code);
      }
      return end(code);
    }

    function trailing(code: Code): State | undefined {
      if (markdownSpace(code)) {
        effects.consume(code);
        return trailing;
      }
      effects.exit(types.whitespace);
      return end(code);
    }

    function end(code: Code): State | undefined {
      if (code !== codes.eof && !markdownLineEnding(code)) return nok(code);
      effects.exit('mathFlowFence');
      return ok(code);
    }
  }

  // Past a line ending, unless the next line is a lazy continuation, which
  // means the container around the block (a quote, a list item) has ended.
  function tokenizeNonLazyLine(effects: Effects, ok: State, nok: State): State {
    return (code) => {
      effects.enter(types.lineEnding);
      effects.consume(code);
      effects.exit(types.lineEnding);
      return (next) => (lazyLine() ? nok(next) : ok(next));
    };
  }
}

const texFlow: Construct = {
  name: 'mathTexFlow',
  tokenize: tokenizeTexFlow,
  concrete: true,
};

export const texMath: Extension = {
  flow: { [codes.backslash]: texFlow },
  text: { [codes.backslash]: texText },
};

/** remark plugin for {@link texMath}; `remark-math` must run alongside it. */
export function remarkTexMath(this: Processor) {
  addMicromarkExtension(this, texMath);
}
