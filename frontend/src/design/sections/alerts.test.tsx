import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

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

describe('gallery Alerts', () => {
  it.each([
    ['BadgeSection', BadgeSection],
    ['ButtonSection', ButtonSection],
  ] as const)(
    '%s passes no icon child: every Alert icon is the one Alert draws',
    async (_name, Component) => {
      await act(async () => root.render(<Component />));
      const alerts = Array.from(
        container.querySelectorAll('[data-slot="alert"]'),
      );
      expect(alerts.length).toBeGreaterThan(0);
      alerts.forEach((alert) => {
        const svgs = Array.from(alert.querySelectorAll(':scope > svg'));
        svgs.forEach((svg) =>
          expect(svg.getAttribute('data-slot')).toBe('alert-icon'),
        );
      });
    },
  );
});
