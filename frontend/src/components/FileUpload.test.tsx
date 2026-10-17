import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { FileUpload } from './FileUpload';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function makeFile(name: string, type: string, bytes = 10): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

async function selectFiles(container: HTMLElement, files: File[]) {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error('no file input');
  Object.defineProperty(input, 'files', { value: files, configurable: true });
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

/**
 * Wait until `predicate` holds, yielding a macrotask between checks.
 *
 * react-dropzone resolves dropped files over its own promise chain, so the
 * work a `change` event kicks off is not done when `selectFiles` returns and
 * takes an unknown number of ticks. Waiting a fixed tick made the preview
 * assertions below fail on most runs; wait for the effect instead.
 */
async function waitFor(predicate: () => boolean, timeout = 2000) {
  const deadline = Date.now() + timeout;
  while (!predicate()) {
    if (Date.now() > deadline) {
      throw new Error('waitFor: condition still false after 2000ms');
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });
  }
}

describe('FileUpload', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('renders on the shared Dropzone with the upload prompt', async () => {
    await act(async () => {
      root.render(<FileUpload onUpload={vi.fn()} />);
    });
    const zone = container.querySelector('[data-slot="dropzone"]');
    expect(zone).not.toBeNull();
    expect(zone?.getAttribute('data-size')).toBe('default');
    expect(container.textContent).toContain(
      'components.fileUpload.clickToUpload',
    );
    expect(container.textContent).toContain('components.fileUpload.fileTypes');
  });

  it('passes the compact size through', async () => {
    await act(async () => {
      root.render(<FileUpload onUpload={vi.fn()} size="compact" />);
    });
    expect(
      container
        .querySelector('[data-slot="dropzone"]')
        ?.getAttribute('data-size'),
    ).toBe('compact');
  });

  it('shows the current image inside a tile until a new one is picked', async () => {
    await act(async () => {
      root.render(
        <FileUpload
          onUpload={vi.fn()}
          size="tile"
          showPreview
          currentImage="https://example.com/agent.png"
          uploadText="Avatar"
        />,
      );
    });
    const zone = container.querySelector('[data-slot="dropzone"]')!;
    expect(zone.getAttribute('data-size')).toBe('tile');
    const img = zone.querySelector('img')!;
    expect(img.getAttribute('src')).toBe('https://example.com/agent.png');
    expect(img.className).toContain('object-cover');
    expect(container.textContent).not.toContain(
      'components.fileUpload.fileTypes',
    );
  });

  it('renders highlighted upload text segments', async () => {
    await act(async () => {
      root.render(
        <FileUpload
          onUpload={vi.fn()}
          uploadText={[
            { text: 'Click to upload', highlight: true },
            { text: ' or drag and drop' },
          ]}
        />,
      );
    });
    const highlighted = Array.from(container.querySelectorAll('span')).find(
      (s) => s.textContent === 'Click to upload',
    );
    expect(highlighted?.className).toContain('text-primary');
  });

  it.each(['tile', 'default'] as const)(
    'draws the focus ring on the %s preview Remove button',
    async (size) => {
      await act(async () => {
        root.render(<FileUpload onUpload={vi.fn()} size={size} showPreview />);
      });
      await selectFiles(container, [makeFile('logo.png', 'image/png')]);
      const selector = 'button[aria-label="components.fileUpload.remove"]';
      await waitFor(() => container.querySelector(selector) !== null);
      const remove = container.querySelector<HTMLButtonElement>(selector);
      expect(remove).not.toBeNull();
      expect(remove!.className).toContain('focus-visible:ring-3');
      expect(remove!.className).toContain('outline-none');
    },
  );

  it('calls onUpload with a valid file', async () => {
    const onUpload = vi.fn();
    await act(async () => {
      root.render(<FileUpload onUpload={onUpload} />);
    });
    const file = makeFile('logo.png', 'image/png');
    await selectFiles(container, [file]);
    await waitFor(() => onUpload.mock.calls.length > 0);
    expect(onUpload).toHaveBeenCalledWith([file]);
  });

  it('shows the validator error and does not upload', async () => {
    const onUpload = vi.fn();
    await act(async () => {
      root.render(
        <FileUpload
          onUpload={onUpload}
          validator={() => ({ isValid: false, error: 'Bad image' })}
        />,
      );
    });
    await selectFiles(container, [makeFile('logo.png', 'image/png')]);
    await waitFor(() => container.querySelector('.text-destructive') !== null);
    expect(onUpload).not.toHaveBeenCalled();
    const error = container.querySelector('.text-destructive');
    expect(error?.textContent).toContain('Bad image');
  });
});
