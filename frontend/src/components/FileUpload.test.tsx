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
  // react-dropzone resolves the selected files asynchronously.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
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

  it('calls onUpload with a valid file', async () => {
    const onUpload = vi.fn();
    await act(async () => {
      root.render(<FileUpload onUpload={onUpload} />);
    });
    const file = makeFile('logo.png', 'image/png');
    await selectFiles(container, [file]);
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
    expect(onUpload).not.toHaveBeenCalled();
    const error = container.querySelector('.text-destructive');
    expect(error?.textContent).toContain('Bad image');
  });
});
