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

  const render = async (icon: string, title?: string) => {
    await act(async () => {
      root.render(<ConnectorIcon icon={icon} title={title} />);
    });
  };

  it('renders a preset mark instead of the plug fallback', async () => {
    await render('huggingface', 'Hugging Face');

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-label')).toBe('Hugging Face');
    // The Hugging Face emoji mark is multi-colour, so it keeps its own fills
    // rather than inheriting currentColor.
    expect(svg?.querySelector('path[fill="#FFD21E"]')).not.toBeNull();
  });

  it('falls back to a plug for an unknown icon', async () => {
    await render('not_a_connector');

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    expect(svg?.querySelector('path[fill="#FFD21E"]')).toBeNull();
  });
});
