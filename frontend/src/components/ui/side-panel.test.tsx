import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const media = { isMobile: false, isDesktop: true };
// Counts the panel's renders: it reads the media query once per render.
const mediaReads = { count: 0 };
vi.mock('../../hooks', () => ({
  useMediaQuery: () => {
    mediaReads.count += 1;
    return media;
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
  type SidePanelProps,
} from './side-panel';
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
  props: Partial<SidePanelProps> = {},
  header: Partial<React.ComponentProps<typeof PanelHeader>> = {},
) => (
  <SidePanel
    open
    onOpenChange={() => undefined}
    aria-describedby={undefined}
    {...(props as object)}
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

  it('never offers Expand, and its types refuse expandable', async () => {
    await render(
      // @ts-expect-error expandable is docked-only
      <SidePanel open onOpenChange={() => undefined} expandable="artifact">
        <PanelHeader title="renewal-note.md" />
      </SidePanel>,
    );
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
    // Above the app's floating top actions (Share, account), which it covers.
    expect(el.className.split(' ')).toEqual(
      expect.arrayContaining(['relative', 'z-20']),
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

  // Live check [#16]: closing left focus on <body>.
  it('gives focus back to what opened it when it closes', async () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    try {
      opener.focus();
      await render(panel({ variant: 'docked', open: false }));
      await render(
        <SidePanel variant="docked" open onOpenChange={() => undefined}>
          <PanelHeader title="renewal-note.md" />
          <PanelBody>
            <input data-testid="field" />
          </PanelBody>
        </SidePanel>,
      );
      const field = document.querySelector<HTMLInputElement>(
        '[data-testid="field"]',
      )!;
      field.focus();
      expect(document.activeElement).toBe(field);
      await render(panel({ variant: 'docked', open: false }));
      expect(document.activeElement).toBe(opener);
    } finally {
      opener.remove();
    }
  });

  // Live check C07: a strip's Next opened it, then went away.
  it('focuses its fallback when what opened it is gone', async () => {
    const opener = document.createElement('button');
    const wand = document.createElement('button');
    document.body.append(opener, wand);
    try {
      opener.focus();
      await render(panel({ variant: 'docked', open: false }));
      await render(panel({ variant: 'docked', focusFallback: () => wand }));
      button('sidePanel.close')!.focus();
      opener.remove();
      await render(
        panel({ variant: 'docked', open: false, focusFallback: () => wand }),
      );
      expect(document.activeElement).toBe(wand);
    } finally {
      opener.remove();
      wand.remove();
    }
  });

  it('leaves focus alone on close when it is outside the panel', async () => {
    const opener = document.createElement('button');
    const elsewhere = document.createElement('input');
    document.body.append(opener, elsewhere);
    try {
      opener.focus();
      await render(panel({ variant: 'docked', open: false }));
      await render(panel({ variant: 'docked' }));
      elsewhere.focus();
      await render(panel({ variant: 'docked', open: false }));
      expect(document.activeElement).toBe(elsewhere);
    } finally {
      opener.remove();
      elsewhere.remove();
    }
  });

  it('is always 480px compact: wide is a modal-only size', async () => {
    await render(
      <SidePanel
        variant="docked"
        open
        onOpenChange={() => undefined}
        // @ts-expect-error a docked panel has no size
        size="wide"
      >
        <PanelHeader title="renewal-note.md" />
      </SidePanel>,
    );
    const classes = aside()!.className.split(' ');
    expect(classes).toContain('w-120');
    expect(classes).not.toContain('w-[800px]');
  });

  it('grows in from the right edge without overflowing its host', async () => {
    await render(panel({ variant: 'docked' }));
    const classes = aside()!.className.split(' ');
    // Width, not a transform: an offscreen transform overflows the host,
    // which then scrolls sideways when the panel focuses a field.
    expect(classes).toEqual(
      expect.arrayContaining(['starting:w-0', 'overflow-clip']),
    );
    expect(aside()!.className).not.toContain('slide-in');
    const content = aside()!.querySelector<HTMLElement>(
      '[data-slot="side-panel-content"]',
    )!;
    // The content keeps its width, pinned right, so it slides rather than
    // reflowing while the panel grows.
    expect(content.className.split(' ')).toEqual(
      expect.arrayContaining(['absolute', 'right-0', 'min-w-120']),
    );
  });

  describe('closing', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('shrinks out, inert, then unmounts', async () => {
      await render(panel({ variant: 'docked' }));
      await render(panel({ variant: 'docked', open: false }));
      const el = aside()!;
      expect(el.dataset.state).toBe('closed');
      expect(el.className.split(' ')).toContain('w-0');
      expect(el.hasAttribute('inert')).toBe(true);
      await act(async () => vi.advanceTimersByTime(300));
      expect(aside()).toBeNull();
    });

    it('keeps its last content while it shrinks out', async () => {
      await render(panel({ variant: 'docked' }));
      await render(
        <SidePanel variant="docked" open={false} onOpenChange={() => {}}>
          {null}
        </SidePanel>,
      );
      expect(aside()!.textContent).toContain('renewal-note.md');
    });

    it('keeps the content it last showed open, not what it first opened with', async () => {
      await render(panel({ variant: 'docked' }));
      await render(panel({ variant: 'docked' }, { title: 'later-note.md' }));
      await render(
        <SidePanel variant="docked" open={false} onOpenChange={() => {}}>
          {null}
        </SidePanel>,
      );
      expect(aside()!.textContent).toContain('later-note.md');
    });

    it('fills itself once grown in, so a narrow host never clips it', async () => {
      const content = () =>
        aside()!
          .querySelector<HTMLElement>('[data-slot="side-panel-content"]')!
          .className.split(' ');
      await render(panel({ variant: 'docked' }));
      // While it moves the content keeps the compact width and slides.
      expect(content()).toContain('min-w-120');
      await act(async () => vi.advanceTimersByTime(300));
      // At rest it is the panel's width: a host narrower than 480px, or the
      // panel's own border, would clip its left side.
      expect(content()).toContain('w-full');
      expect(content()).not.toContain('min-w-120');
      await render(panel({ variant: 'docked', open: false }));
      expect(content()).toContain('min-w-120');
    });

    it('tells the page once it has shrunk out', async () => {
      const onClosed = vi.fn();
      await render(panel({ variant: 'docked', onClosed }));
      await render(panel({ variant: 'docked', open: false, onClosed }));
      await act(async () => vi.advanceTimersByTime(200));
      // A page render mid-exit, with a new callback, doesn't restart it.
      const latest = vi.fn();
      await render(panel({ variant: 'docked', open: false, onClosed: latest }));
      await act(async () => vi.advanceTimersByTime(99));
      expect(latest).not.toHaveBeenCalled();
      await act(async () => vi.advanceTimersByTime(1));
      expect(aside()).toBeNull();
      expect(latest).toHaveBeenCalledTimes(1);
      expect(onClosed).not.toHaveBeenCalled();
    });

    it('unmounts without the shrink under reduced motion', async () => {
      vi.stubGlobal('matchMedia', (query: string) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
      }));
      try {
        await render(panel({ variant: 'docked' }));
        await render(panel({ variant: 'docked', open: false }));
        await act(async () => vi.advanceTimersByTime(0));
        expect(aside()).toBeNull();
      } finally {
        vi.unstubAllGlobals();
      }
    });

    it('renders once per page render while open', async () => {
      // A new content element on every page render must not re-render the
      // panel a second time to remember it.
      await render(panel({ variant: 'docked' }));
      mediaReads.count = 0;
      await render(panel({ variant: 'docked' }));
      expect(mediaReads.count).toBe(1);
    });

    it('stays open when reopened mid-exit', async () => {
      await render(panel({ variant: 'docked' }));
      await render(panel({ variant: 'docked', open: false }));
      await render(panel({ variant: 'docked' }));
      await act(async () => vi.advanceTimersByTime(300));
      expect(aside()!.dataset.state).toBe('open');
      expect(aside()!.hasAttribute('inert')).toBe(false);
    });
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
      expect.arrayContaining(['absolute', 'inset-0', 'z-20']),
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
