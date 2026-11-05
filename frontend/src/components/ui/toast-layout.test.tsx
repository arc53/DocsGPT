import { act, useRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  createToastAvoidRegistry,
  TOAST_STACK_BOTTOM_PX,
  TOAST_STACK_TOP_RESERVE_PX,
  ToastAvoidContext,
  toastStackLayout,
  useAvoidToasts,
} from './toast-layout';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const box = (left: number, top: number, width: number, height: number) => ({
  left,
  top,
  right: left + width,
  width,
  height,
});

describe('toastStackLayout', () => {
  // A 1440x900 window: the stack is the right-most 288px, the composer
  // ends at 1248px with its top at 780px.
  const stack = { left: 1144, right: 1432 };

  it('sits at the corner when nothing is below it', () => {
    expect(toastStackLayout(stack, [], 900)).toEqual({
      bottom: TOAST_STACK_BOTTOM_PX,
      maxHeight: 900 - TOAST_STACK_BOTTOM_PX - TOAST_STACK_TOP_RESERVE_PX,
    });
  });

  it('rises above a composer it would overlap', () => {
    const composer = box(480, 780, 768, 100);
    expect(toastStackLayout(stack, [composer], 900)).toEqual({
      bottom: 120,
      maxHeight: 900 - 120 - TOAST_STACK_TOP_RESERVE_PX,
    });
  });

  it('stays at the corner beside a composer that ends before it', () => {
    const composer = box(400, 780, 700, 100);
    expect(toastStackLayout(stack, [composer], 900).bottom).toBe(
      TOAST_STACK_BOTTOM_PX,
    );
  });

  it('ignores a composer that is not laid out, and clears the highest one', () => {
    const hidden = box(0, 0, 0, 0);
    const low = box(1000, 800, 400, 80);
    const high = box(1100, 600, 300, 80);
    expect(toastStackLayout(stack, [hidden, low, high], 900).bottom).toBe(300);
  });

  it('never gives a negative height', () => {
    const composer = box(1100, 40, 300, 800);
    expect(toastStackLayout(stack, [composer], 900).maxHeight).toBe(0);
  });
});

describe('useAvoidToasts', () => {
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

  function Composer() {
    const ref = useRef<HTMLDivElement>(null);
    useAvoidToasts(ref);
    return <div ref={ref} data-testid="composer" />;
  }

  it('registers the element while mounted and tells listeners', async () => {
    const registry = createToastAvoidRegistry();
    const listener = vi.fn();
    registry.subscribe(listener);
    await act(async () => {
      root.render(
        <ToastAvoidContext.Provider value={registry}>
          <Composer />
        </ToastAvoidContext.Provider>,
      );
    });
    expect(registry.elements()).toEqual([
      container.querySelector('[data-testid="composer"]'),
    ]);
    expect(listener).toHaveBeenCalledTimes(1);

    await act(async () => root.render(<></>));
    expect(registry.elements()).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('does nothing outside a provider', async () => {
    await act(async () => root.render(<Composer />));
    expect(container.querySelector('[data-testid="composer"]')).not.toBeNull();
  });
});
