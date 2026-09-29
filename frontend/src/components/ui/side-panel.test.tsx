import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const media = { isMobile: false, isDesktop: true };
vi.mock('../../hooks', () => ({
  useMediaQuery: () => media,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { PanelBody, PanelFooter, PanelHeader, SidePanel } from './side-panel';
import { TooltipProvider } from './tooltip';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  media.isMobile = false;
  media.isDesktop = true;
});

const render = async (element: React.ReactElement) => {
  await act(async () =>
    root.render(<TooltipProvider>{element}</TooltipProvider>),
  );
};

const button = (label: string) =>
  document.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

const aside = () =>
  document.querySelector<HTMLElement>('[data-slot="side-panel"]');

const click = async (el: HTMLElement | null) => {
  await act(async () => el!.click());
};

const panel = (
  props: Partial<React.ComponentProps<typeof SidePanel>> = {},
  header: Partial<React.ComponentProps<typeof PanelHeader>> = {},
) => (
  <SidePanel
    open
    onOpenChange={() => undefined}
    aria-describedby={undefined}
    {...props}
  >
    <PanelHeader title="renewal-note.md" {...header} />
    <PanelBody>Body</PanelBody>
  </SidePanel>
);

describe('SidePanel variant="modal"', () => {
  it('is a right Sheet over the blurred scrim, named by its header', async () => {
    await render(panel());
    const content = document.querySelector<HTMLElement>(
      '[data-slot="sheet-content"]',
    )!;
    expect(content.dataset.side).toBe('right');
    expect(
      document.querySelector('[data-slot="sheet-overlay"]')!.className,
    ).toContain('backdrop-blur-xs');
    const labelledBy = content.getAttribute('aria-labelledby')!;
    expect(document.getElementById(labelledBy)?.textContent).toBe(
      'renewal-note.md',
    );
    expect(aside()).toBeNull();
  });

  it('draws one X, in the header row, that closes it', async () => {
    const onOpenChange = vi.fn();
    await render(panel({ onOpenChange }));
    const closes = document.querySelectorAll(
      'button[aria-label="sidePanel.close"]',
    );
    expect(closes).toHaveLength(1);
    expect(closes[0].closest('[data-slot="panel-header"]')).not.toBeNull();
    await click(button('sidePanel.close'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('never offers Expand', async () => {
    await render(panel({ expandable: 'artifact' }));
    expect(button('sidePanel.expand')).toBeNull();
  });
});

describe('SidePanel variant="docked"', () => {
  it('sits in the page beside the content, with no scrim', async () => {
    await render(panel({ variant: 'docked' }));
    const el = aside()!;
    expect(el.tagName).toBe('ASIDE');
    expect(el.className.split(' ')).toEqual(
      expect.arrayContaining(['bg-background', 'border-l', 'w-120']),
    );
    expect(document.querySelector('[data-slot="sheet-overlay"]')).toBeNull();
    const labelledBy = el.getAttribute('aria-labelledby')!;
    expect(document.getElementById(labelledBy)?.textContent).toBe(
      'renewal-note.md',
    );
  });

  it('renders nothing while closed', async () => {
    await render(panel({ variant: 'docked', open: false }));
    expect(aside()).toBeNull();
  });

  it('closes from its X', async () => {
    const onOpenChange = vi.fn();
    await render(panel({ variant: 'docked', onOpenChange }));
    await click(button('sidePanel.close'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('takes its starting width from size', async () => {
    await render(panel({ variant: 'docked', size: 'wide' }));
    expect(aside()!.className.split(' ')).toContain('w-[800px]');
  });

  it('slides in from the right', async () => {
    await render(panel({ variant: 'docked' }));
    expect(aside()!.className).toContain('slide-in-from-right');
    expect(aside()!.className).not.toContain('slide-out');
  });

  it('disappears at once when it closes, with no exit animation', async () => {
    await render(panel({ variant: 'docked' }));
    await render(panel({ variant: 'docked', open: false }));
    expect(aside()).toBeNull();
  });

  it('has no Expand unless expandable', async () => {
    await render(panel({ variant: 'docked' }));
    expect(button('sidePanel.expand')).toBeNull();
  });

  it('steps compact, half, full and back from one button', async () => {
    await render(panel({ variant: 'docked', expandable: 'artifact' }));
    expect(aside()!.dataset.width).toBe('compact');

    await click(button('sidePanel.expand'));
    expect(aside()!.dataset.width).toBe('half');
    // Half of a narrow host never shrinks it below its compact size.
    expect(aside()!.className.split(' ')).toEqual(
      expect.arrayContaining(['w-1/2', 'min-w-120']),
    );

    await click(button('sidePanel.expand'));
    expect(aside()!.dataset.width).toBe('full');
    expect(aside()!.className.split(' ')).toEqual(
      expect.arrayContaining(['absolute', 'inset-0']),
    );

    await click(button('sidePanel.collapse'));
    expect(aside()!.dataset.width).toBe('compact');
    expect(aside()!.className.split(' ')).toContain('w-120');
  });

  it('remembers the last width per surface', async () => {
    await render(panel({ variant: 'docked', expandable: 'artifact' }));
    await click(button('sidePanel.expand'));
    await act(async () => root.unmount());
    root = createRoot(container);

    await render(panel({ variant: 'docked', expandable: 'artifact' }));
    expect(aside()!.dataset.width).toBe('half');

    await act(async () => root.unmount());
    root = createRoot(container);
    await render(panel({ variant: 'docked', expandable: 'workflow-node' }));
    expect(aside()!.dataset.width).toBe('compact');
  });

  it('re-reads the width when the slot switches surface', async () => {
    localStorage.setItem('docsgpt-side-panel:artifact', 'full');
    await render(panel({ variant: 'docked' }));
    expect(aside()!.dataset.width).toBe('compact');
    await render(panel({ variant: 'docked', expandable: 'artifact' }));
    expect(aside()!.dataset.width).toBe('full');
  });

  it('opens compact when storage is unavailable', async () => {
    const spy = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });
    await render(panel({ variant: 'docked', expandable: 'artifact' }));
    expect(aside()!.dataset.width).toBe('compact');
    spy.mockRestore();
  });

  it('is a full-width right sheet on a phone', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    await render(panel({ variant: 'docked', expandable: 'artifact' }));
    expect(aside()).toBeNull();
    const content = document.querySelector<HTMLElement>(
      '[data-slot="sheet-content"]',
    )!;
    expect(content.dataset.side).toBe('right');
    expect(content.className.split(' ')).toContain('w-full');
    expect(button('sidePanel.expand')).toBeNull();
  });

  it('opens on a phone without a focus ring on its first control', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    await render(panel({ variant: 'docked' }));
    expect(document.activeElement).not.toBe(button('sidePanel.close'));
  });
});

describe('PanelHeader', () => {
  it('puts leading, actions and a Back button in the one row', async () => {
    const onBack = vi.fn();
    await render(
      panel(
        { variant: 'docked' },
        {
          description: 'Note · updated just now',
          leading: <span data-testid="tile" />,
          actions: <button type="button">Download</button>,
          onBack,
        },
      ),
    );
    const header = document.querySelector('[data-slot="panel-header"]')!;
    expect(header.querySelector('[data-testid="tile"]')).not.toBeNull();
    expect(header.textContent).toContain('Note · updated just now');
    expect(header.textContent).toContain('Download');
    await click(button('sidePanel.back'));
    expect(onBack).toHaveBeenCalled();
  });

  it('is followed by a separator and never scrolls with the body', async () => {
    await render(panel({ variant: 'docked' }));
    const header = document.querySelector('[data-slot="panel-header"]')!;
    expect(header.className.split(' ')).toContain('shrink-0');
    expect(header.nextElementSibling?.getAttribute('data-slot')).toBe(
      'separator',
    );
    const body = document.querySelector('[data-slot="panel-body"]')!;
    expect(body.className.split(' ')).toEqual(
      expect.arrayContaining([
        'min-h-0',
        'flex-1',
        'overflow-y-auto',
        'flex-col',
        'gap-6',
      ]),
    );
  });
});

describe('PanelBody scroll={false}', () => {
  it('lets the content own its scroller', async () => {
    await render(
      <SidePanel open onOpenChange={() => undefined} variant="docked">
        <PanelHeader title="Artifact" />
        <PanelBody scroll={false}>Body</PanelBody>
      </SidePanel>,
    );
    const body = document.querySelector('[data-slot="panel-body"]')!;
    expect(body.className.split(' ')).toContain('overflow-hidden');
    expect(body.className.split(' ')).not.toContain('overflow-y-auto');
  });
});

describe('PanelFooter', () => {
  it('is a separated, right-aligned action row', async () => {
    await render(
      <SidePanel open onOpenChange={() => undefined} variant="docked">
        <PanelHeader title="Details" />
        <PanelBody>Body</PanelBody>
        <PanelFooter>
          <button type="button">Save</button>
        </PanelFooter>
      </SidePanel>,
    );
    const footer = document.querySelector('[data-slot="panel-footer"]')!;
    expect(footer.previousElementSibling?.getAttribute('data-slot')).toBe(
      'separator',
    );
    expect(footer.className.split(' ')).toEqual(
      expect.arrayContaining(['justify-end', 'px-6', 'py-4']),
    );
  });
});
