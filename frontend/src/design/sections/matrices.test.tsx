import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { badgeVariantNames } from '@/components/ui/badge';
import { buttonSizeNames, buttonVariantNames } from '@/components/ui/button';

import BadgeSection from './BadgeSection';
import ButtonSection from './ButtonSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

const render = async (element: React.ReactElement) => {
  await act(async () => root.render(element));
};

// The matrix columns: text sizes only (icon and link sizes have their own demos).
const MATRIX_SIZES = buttonSizeNames.filter(
  (size) => !size.startsWith('icon') && size !== 'inline' && size !== 'text',
);

describe('gallery matrices follow the cva config', () => {
  it('the Button matrix has one row per exported variant and one cell per size', async () => {
    await render(<ButtonSection />);
    const matrix = container.querySelector('[data-testid="button-matrix"]');
    expect(matrix).not.toBeNull();
    const rows = Array.from(matrix!.querySelectorAll(':scope > .contents'));
    expect(rows.map((row) => row.firstElementChild?.textContent)).toEqual(
      buttonVariantNames,
    );
    rows.forEach((row, index) => {
      const buttons = Array.from(row.querySelectorAll('[data-slot="button"]'));
      expect(buttons.map((b) => b.getAttribute('data-size'))).toEqual(
        MATRIX_SIZES,
      );
      buttons.forEach((b) =>
        expect(b.getAttribute('data-variant')).toBe(buttonVariantNames[index]),
      );
    });
  });

  it('lists every Button variant, including the special-purpose ones', () => {
    expect(buttonVariantNames).toEqual(
      expect.arrayContaining(['default', 'link', 'sidebar-item', 'combobox']),
    );
    expect(MATRIX_SIZES).toEqual(['xs', 'sm', 'default', 'lg', 'field']);
  });

  it('shows one Badge per exported variant', async () => {
    await render(<BadgeSection />);
    // The matrix badges are labelled with their own variant name.
    const labels = Array.from(container.querySelectorAll('[data-slot="badge"]'))
      .filter(
        (badge) => badge.textContent === badge.getAttribute('data-variant'),
      )
      .map((badge) => badge.textContent);
    expect(labels).toEqual(badgeVariantNames);
  });
});
