import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { Head } from './Head';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const robots = () =>
  document.head.querySelector<HTMLMetaElement>('meta[name="robots"]');

describe('Head', () => {
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

  it('puts a robots tag in the document head while mounted', () => {
    act(() => root.render(<Head robots="noindex, nofollow" />));
    expect(robots()?.content).toBe('noindex, nofollow');

    act(() => root.render(<></>));
    expect(robots()).toBeNull();
  });

  it('adds no robots tag unless asked', () => {
    act(() => root.render(<Head title="DocsGPT" />));
    expect(robots()).toBeNull();
  });
});
