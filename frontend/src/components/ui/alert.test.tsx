import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Alert, AlertDescription } from './alert';

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

const alertRole = () => container.firstElementChild!.getAttribute('role');

describe('Alert', () => {
  it.each(['default', 'destructive', 'warning', 'info'] as const)(
    'announces %s assertively',
    async (variant) => {
      await render(
        <Alert variant={variant}>
          <AlertDescription>Notice</AlertDescription>
        </Alert>,
      );
      expect(alertRole()).toBe('alert');
    },
  );

  it('announces success politely', async () => {
    await render(
      <Alert variant="success">
        <AlertDescription>Done</AlertDescription>
      </Alert>,
    );
    expect(alertRole()).toBe('status');
  });

  it('lets the caller override the role', async () => {
    await render(<Alert variant="destructive" role="status" />);
    expect(alertRole()).toBe('status');
  });
});
