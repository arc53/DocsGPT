import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useDebouncedValue: (value: unknown) => value,
  useLoaderState: (initial: boolean) => useState(initial),
  useMediaQuery: () => ({ isMobile: false }),
  useOutsideAlerter: () => undefined,
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getDocumentChunks: vi.fn(async () => ({
      ok: true,
      json: async () => ({
        page: 1,
        per_page: 5,
        total: 1,
        chunks: [{ doc_id: 'c1', text: 'Late pickup clause', metadata: {} }],
      }),
    })),
  },
}));

import Chunks from './Chunks';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const setInputValue = (input: HTMLInputElement, value: string) => {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value',
  )!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('Chunks', () => {
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

  const render = async (onFileSelect = vi.fn()) => {
    await act(async () => {
      root.render(
        <Chunks
          documentId="doc"
          documentName="Contracts"
          handleGoBack={vi.fn()}
          onFileSearch={() => [
            { name: 'msa.pdf', path: 'contracts/msa.pdf', isFile: true },
            { name: 'sla.docx', path: 'contracts/sla.docx', isFile: true },
          ]}
          onFileSelect={onFileSelect}
        />,
      );
    });
    return onFileSelect;
  };

  it('picks a file search result with the keyboard', async () => {
    const onFileSelect = await render();
    const input = container.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    expect(input).not.toBeNull();

    await act(async () => setInputValue(input, 'contracts'));
    const items = container.querySelectorAll('[data-slot="command-item"]');
    expect(items).toHaveLength(2);

    await act(async () => {
      input.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }),
      );
    });
    await act(async () => {
      input.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(onFileSelect).toHaveBeenCalledWith('contracts/sla.docx');
  });

  it('renders each chunk tile as a button', async () => {
    await render();
    const tile = container.querySelector<HTMLButtonElement>(
      'button[data-slot="card"]',
    );
    expect(tile).not.toBeNull();
    expect(tile!.textContent).toContain('Late pickup clause');
    expect(tile!.className).not.toContain('hover:scale-105');
  });

  const renderPath = async (props: {
    onPathSelect?: (depth: number) => void;
    handleGoBack?: () => void;
  }) => {
    await act(async () => {
      root.render(
        <Chunks
          documentId="doc"
          documentName="Contracts"
          handleGoBack={props.handleGoBack ?? vi.fn()}
          path="legal/2024/msa.pdf"
          displayPath="legal/2024/msa.pdf"
          onPathSelect={props.onPathSelect}
        />,
      );
    });
  };

  const crumbButton = (label: string) =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="breadcrumb-link"]',
      ),
    ).find((el) => el.textContent === label);

  it('opens the root and parent folders from the path crumbs', async () => {
    const onPathSelect = vi.fn();
    await renderPath({ onPathSelect });

    await act(async () => crumbButton('Contracts')!.click());
    expect(onPathSelect).toHaveBeenLastCalledWith(0);
    await act(async () => crumbButton('2024')!.click());
    expect(onPathSelect).toHaveBeenLastCalledWith(2);
    // The file is the current crumb, not a link.
    expect(crumbButton('msa.pdf')).toBeUndefined();
  });

  it('without onPathSelect the root goes back and folders are text', async () => {
    const handleGoBack = vi.fn();
    await renderPath({ handleGoBack });

    await act(async () => crumbButton('Contracts')!.click());
    expect(handleGoBack).toHaveBeenCalledTimes(1);
    expect(crumbButton('legal')).toBeUndefined();
    expect(crumbButton('2024')).toBeUndefined();
  });
});
