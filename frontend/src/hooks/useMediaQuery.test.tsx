import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useMediaQuery } from './index';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Evaluates min-/max-width queries against a fixed window width.
const mockWidth = (width: number) => {
  vi.stubGlobal('matchMedia', (query: string) => {
    const max = /max-width:\s*([\d.]+)px/.exec(query);
    const min = /min-width:\s*([\d.]+)px/.exec(query);
    const matches =
      (!max || width <= Number(max[1])) && (!min || width >= Number(min[1]));
    return {
      matches,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    };
  });
};

const read = async (width: number) => {
  mockWidth(width);
  let result: ReturnType<typeof useMediaQuery> | undefined;
  function Probe() {
    result = useMediaQuery();
    return null;
  }
  const container = document.createElement('div');
  const root = createRoot(container);
  await act(async () => root.render(<Probe />));
  await act(async () => root.unmount());
  return result!;
};

afterEach(() => vi.unstubAllGlobals());

describe('useMediaQuery', () => {
  it('treats everything below lg (1024px) as mobile', async () => {
    expect(await read(900)).toMatchObject({ isMobile: true, isDesktop: false });
    expect(await read(1023)).toMatchObject({
      isMobile: true,
      isDesktop: false,
    });
  });

  it('is desktop from 1024px', async () => {
    expect(await read(1024)).toMatchObject({
      isMobile: false,
      isDesktop: true,
    });
  });
});
