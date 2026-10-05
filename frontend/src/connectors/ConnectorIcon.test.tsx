import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import ConnectorIcon from './ConnectorIcon';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConnectorIcon', () => {
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

  const render = (node: React.ReactNode) =>
    act(async () => {
      root.render(node);
    });

  it('renders the Resend SVG icon for preset resend', async () => {
    await render(<ConnectorIcon icon="resend" title="Resend" />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-label')).toBe('Resend');
    expect(svg?.getAttribute('viewBox')).toBe('0 0 24 24');
  });

  it('falls back to plug for unknown icons', async () => {
    await render(<ConnectorIcon icon="unknown_custom_server" />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
  });
});
