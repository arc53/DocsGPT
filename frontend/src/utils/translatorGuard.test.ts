import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from 'vitest';

import { installTranslatorGuard } from './translatorGuard';

const native = {
  removeChild: Node.prototype.removeChild,
  insertBefore: Node.prototype.insertBefore,
};

// What Chrome Translate does to a text node: it takes it out of its parent
// and puts the translated text in a <font> in its place.
function translate(text: Text): HTMLElement {
  const font = document.createElement('font');
  font.appendChild(document.createTextNode(`${text.data} (translated)`));
  text.parentNode!.replaceChild(font, text);
  return font;
}

// The same, for translators that move the original node into the wrapper.
function wrap(text: Text): HTMLElement {
  const font = document.createElement('font');
  text.parentNode!.replaceChild(font, text);
  font.appendChild(text);
  return font;
}

describe('without the guard', () => {
  it('throws when removing or inserting around a moved node', () => {
    const parent = document.createElement('div');
    const text = parent.appendChild(document.createTextNode('hello'));
    translate(text);
    expect(() => parent.removeChild(text)).toThrow();
    expect(() =>
      parent.insertBefore(document.createElement('i'), text),
    ).toThrow();
  });
});

describe('installTranslatorGuard', () => {
  let uninstall: () => void;
  let warn: Mock<(message: string) => void>;

  beforeEach(() => {
    warn = vi.fn();
    uninstall = installTranslatorGuard(warn);
  });
  afterEach(() => uninstall());

  it('ignores removeChild of a node the translator took out', () => {
    const parent = document.createElement('div');
    const text = parent.appendChild(document.createTextNode('hello'));
    const font = translate(text);
    expect(parent.removeChild(text)).toBe(text);
    expect(parent.firstChild).toBe(font);
  });

  it('ignores removeChild of a node moved into a <font>', () => {
    const parent = document.createElement('div');
    const text = parent.appendChild(document.createTextNode('hello'));
    const font = wrap(text);
    expect(parent.removeChild(text)).toBe(text);
    expect(text.parentNode).toBe(font);
  });

  it('skips insertBefore when the reference node was moved', () => {
    const parent = document.createElement('div');
    const text = parent.appendChild(document.createTextNode('hello'));
    wrap(text);
    const node = document.createElement('i');
    expect(parent.insertBefore(node, text)).toBe(node);
    expect(node.parentNode).toBeNull();
  });

  it('leaves normal calls unchanged', () => {
    const parent = document.createElement('div');
    const a = parent.appendChild(document.createElement('a'));
    const b = document.createElement('b');
    const c = document.createElement('i');
    expect(parent.insertBefore(b, a)).toBe(b);
    expect(parent.insertBefore(c, null)).toBe(c);
    expect(Array.from(parent.childNodes)).toEqual([b, a, c]);
    expect(parent.removeChild(a)).toBe(a);
    expect(Array.from(parent.childNodes)).toEqual([b, c]);
    expect(warn).not.toHaveBeenCalled();
  });

  it('warns once per page load, naming the method', () => {
    const parent = document.createElement('div');
    const first = parent.appendChild(document.createTextNode('one'));
    const second = parent.appendChild(document.createTextNode('two'));
    translate(first);
    translate(second);
    parent.removeChild(first);
    parent.removeChild(second);
    parent.insertBefore(document.createElement('i'), first);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain('removeChild');
  });

  it('installs once, and uninstalling restores the native methods', () => {
    const guarded = Node.prototype.removeChild;
    expect(guarded).not.toBe(native.removeChild);
    // A second install (HMR re-running main.tsx) neither stacks nor undoes it.
    installTranslatorGuard(warn)();
    expect(Node.prototype.removeChild).toBe(guarded);
    uninstall();
    expect(Node.prototype.removeChild).toBe(native.removeChild);
    expect(Node.prototype.insertBefore).toBe(native.insertBefore);
  });
});
