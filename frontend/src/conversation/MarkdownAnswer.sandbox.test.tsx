import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({ useDarkTheme: () => [false, vi.fn()] }));
vi.mock('../components/MermaidRenderer', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));

import MarkdownAnswer from './MarkdownAnswer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const artifacts = [
  {
    id: '9d28fc58-f02f-4d78-a45d-143f60d580e4',
    label: 'summer_sweep_up.pdf',
    toolName: 'artifact_generator',
    ref: 'A3',
  },
];

describe('MarkdownAnswer sandbox: links', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function render(content: string, onOpenArtifact = vi.fn()) {
    act(() => {
      root.render(
        <MarkdownAnswer
          content={content}
          artifacts={artifacts}
          onOpenArtifact={onOpenArtifact}
        />,
      );
    });
    return onOpenArtifact;
  }

  it('renders an artifact sandbox link as a button that opens the artifact', () => {
    const onOpenArtifact = render(
      '[Download the PDF](sandbox:/artifact/A3)',
      vi.fn(),
    );

    expect(container.querySelector('a')).toBeNull();
    const button = container.querySelector('button');
    expect(button?.textContent).toBe('Download the PDF');

    act(() => {
      button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onOpenArtifact).toHaveBeenCalledWith({
      id: '9d28fc58-f02f-4d78-a45d-143f60d580e4',
      toolName: 'artifact_generator',
    });
  });

  // Observed live against gpt-5.6-terra with no prompt rule in place.
  it('renders an artifact: ref as the chip button too', () => {
    const onOpenArtifact = render(
      'Your report is ready: [Download **Q3 Notes**](artifact:A3)',
      vi.fn(),
    );
    expect(container.querySelector('a')).toBeNull();
    act(() => {
      container
        .querySelector('button')
        ?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onOpenArtifact).toHaveBeenCalledOnce();
  });

  it('recovers a fabricated /mnt/data path by filename', () => {
    const onOpenArtifact = render(
      '[Download](sandbox:/mnt/data/summer_sweep_up.pdf)',
      vi.fn(),
    );
    act(() => {
      container
        .querySelector('button')
        ?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onOpenArtifact).toHaveBeenCalledOnce();
  });

  // Before the fix this rendered `<a href="" target="_blank">`, which reopens
  // the app in a new tab — the "the download failed" experience.
  it('renders an unresolvable sandbox link as plain text, never an anchor', () => {
    render('[Download the PDF](sandbox:/tmp/never_existed.pdf)');

    expect(container.querySelector('a')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
    expect(container.textContent).toContain('Download the PDF');
  });

  // Renders mid-sentence, so it must not become a filled 36px pill with
  // violet text on a violet background, and must wrap with the prose.
  it('renders the artifact link inline, not as a filled pill', () => {
    render('Here is [the report](artifact:A3) for you.');
    const button = container.querySelector('button');
    const className = button?.getAttribute('class') ?? '';
    expect(className).not.toMatch(/\bbg-primary\b/);
    expect(className).not.toMatch(/\bh-9\b/);
    expect(className).not.toMatch(/\bwhitespace-nowrap\b/);
    expect(className).toContain('whitespace-normal');
  });

  it('leaves ordinary links alone', () => {
    render('[docs](https://docs.docsgpt.cloud/)');

    const anchor = container.querySelector('a');
    expect(anchor?.getAttribute('href')).toBe('https://docs.docsgpt.cloud/');
    expect(anchor?.getAttribute('target')).toBe('_blank');
  });

  it('still blocks javascript: urls', () => {
    render('[click](javascript:alert&#40;1&#41;)');
    expect(container.querySelector('a')?.getAttribute('href')).toBe('');
  });
});
