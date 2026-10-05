import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { Badge } from '../components/ui/badge';
import ConnectorTile from './ConnectorTile';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConnectorTile', () => {
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

  it('is one button with the icon and title in its header row', async () => {
    const onClick = vi.fn();
    await render(
      <ConnectorTile
        icon={<span data-testid="icon" />}
        title="Telegram"
        description="Send messages."
        badges={<Badge variant="success">Connected</Badge>}
        footer="Alerts bot"
        onClick={onClick}
        testId="tile"
      />,
    );
    const tile = container.querySelector<HTMLButtonElement>(
      '[data-testid="tile"]',
    )!;
    expect(tile.tagName).toBe('BUTTON');
    expect(tile.dataset.variant).toBe('filled');
    expect(tile.dataset.interactive).toBe('true');
    const header = tile.querySelector('[data-slot="card-header"]')!;
    expect(header.querySelector('[data-testid="icon"]')).not.toBeNull();
    expect(header.textContent).toBe('Telegram');
    // No heading inside a clickable tile.
    expect(tile.querySelector('h2, h3')).toBeNull();
    const description = tile.querySelector('[data-slot="card-description"]')!;
    expect(description.className).toContain('line-clamp-2');
    expect(description.hasAttribute('title')).toBe(false);
    expect(tile.querySelector('[data-slot="card-footer"]')!.textContent).toBe(
      'Alerts bot',
    );
    await act(async () => tile.click());
    expect(onClick).toHaveBeenCalled();
  });

  it('holds a menu in the header and names its title as a heading when not a button', async () => {
    await render(
      <ConnectorTile
        icon={<span />}
        title="Memory"
        titleAs="h3"
        menu={<button type="button">menu</button>}
        testId="tile"
      />,
    );
    const tile = container.querySelector<HTMLElement>('[data-testid="tile"]')!;
    expect(tile.tagName).toBe('DIV');
    expect(tile.dataset.interactive).toBeUndefined();
    expect(tile.querySelector('h3')?.textContent).toBe('Memory');
    expect(tile.querySelector('[data-slot="card-action"]')?.textContent).toBe(
      'menu',
    );
    // Nothing to show: no empty badge row and no footer.
    expect(tile.querySelector('[data-slot="card-footer"]')).toBeNull();
    expect(tile.querySelector('[data-slot="tile-badges"]')).toBeNull();
  });

  it('is an outline choice in a picker', async () => {
    await render(
      <ConnectorTile
        variant="outline"
        icon={<span />}
        title="MCP server"
        onClick={vi.fn()}
        testId="tile"
      />,
    );
    const tile = container.querySelector<HTMLElement>('[data-testid="tile"]')!;
    expect(tile.dataset.variant).toBe('outline');
    expect(tile.dataset.padding).toBe('lg');
  });

  it('greys out and ignores clicks when disabled', async () => {
    const onClick = vi.fn();
    await render(
      <ConnectorTile
        icon={<span />}
        title="Brave"
        onClick={onClick}
        disabled
        testId="tile"
      />,
    );
    const tile = container.querySelector<HTMLButtonElement>(
      '[data-testid="tile"]',
    )!;
    expect(tile.disabled).toBe(true);
    expect(tile.dataset.interactive).toBeUndefined();
  });
});
