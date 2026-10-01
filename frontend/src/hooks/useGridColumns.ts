import { useEffect, useState } from 'react';

// The tile grid's breakpoints: grid-cols-1 sm:grid-cols-2 lg:grid-cols-3
// xl:grid-cols-4 (Tailwind's sm, lg and xl).
const STEPS: Array<[query: string, columns: number]> = [
  ['(min-width: 1280px)', 4],
  ['(min-width: 1024px)', 3],
  ['(min-width: 640px)', 2],
];

const current = (): number => {
  if (typeof window === 'undefined' || !window.matchMedia) return 4;
  const hit = STEPS.find(([query]) => window.matchMedia(query).matches);
  return hit ? hit[1] : 1;
};

/**
 * How many columns the standard tile grid shows at the current width, so a
 * section can cap itself at whole rows (two rows: 2, 4, 6 or 8 tiles).
 *
 * Returns:
 *   1 to 4, updated as the window crosses a breakpoint.
 */
export function useGridColumns(): number {
  const [columns, setColumns] = useState(current);

  useEffect(() => {
    if (!window.matchMedia) return;
    const lists = STEPS.map(([query]) => window.matchMedia(query));
    const update = () => setColumns(current());
    lists.forEach((list) => list.addEventListener?.('change', update));
    return () =>
      lists.forEach((list) => list.removeEventListener?.('change', update));
  }, []);

  return columns;
}
