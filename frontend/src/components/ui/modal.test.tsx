import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const media = { isMobile: false, isDesktop: true };
vi.mock('../../hooks', () => ({
  useMediaQuery: () => media,
}));

import { Button } from './button';
import { Modal, ModalActions } from './modal';

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

const content = () =>
  document.querySelector<HTMLElement>('[data-slot="modal-content"]')!;

describe('Modal header', () => {
  it('draws the title at 20px with the description 8px under it', async () => {
    await render(
      <Modal
        open
        onOpenChange={() => undefined}
        title="Create access token"
        description="The token acts as you."
      >
        Body
      </Modal>,
    );
    const title = document.querySelector('[data-slot="dialog-title"]')!;
    expect(title.className).toContain('text-xl');
    expect(title.className).toContain('leading-tight');
    expect(title.className).not.toContain('text-lg');
    const description = document.querySelector(
      '[data-slot="dialog-description"]',
    )!;
    expect(description.className).toContain('mt-2');
    // One flex item for both, so the column's gap-4 doesn't add to mt-2.
    expect(title.parentElement).toBe(description.parentElement);
    expect(title.parentElement).not.toBe(content());
  });
});

describe('Modal footer', () => {
  it('stacks on phones and sits in a right-aligned row from sm up', async () => {
    await render(
      <Modal
        open
        onOpenChange={() => undefined}
        title="Create a team"
        footer={<Button>Create</Button>}
      >
        Body
      </Modal>,
    );
    const footer = document.querySelector('[data-slot="modal-footer"]')!;
    const classes = footer.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'flex-col-reverse',
        'gap-3',
        'sm:flex-row',
        'sm:justify-end',
      ]),
    );
  });
});

describe('ModalActions', () => {
  const renderActions = async (
    props: Partial<React.ComponentProps<typeof ModalActions>> = {},
  ) =>
    render(
      <Modal
        open
        onOpenChange={() => undefined}
        title="Create access token"
        footer={
          <ModalActions
            cancelLabel="Cancel"
            onCancel={() => undefined}
            submitLabel="Create token"
            onSubmit={() => undefined}
            {...props}
          />
        }
      >
        Body
      </Modal>,
    );

  const footerButtons = () =>
    Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        '[data-slot="modal-footer"] button',
      ),
    );

  it('renders a ghost Cancel and a primary submit, both lg pills', async () => {
    await renderActions();
    const [cancel, submit] = footerButtons();
    expect(cancel.textContent).toBe('Cancel');
    expect(cancel.dataset.variant).toBe('ghost');
    expect(submit.textContent).toBe('Create token');
    expect(submit.dataset.variant).toBe('default');
    for (const button of [cancel, submit]) {
      expect(button.dataset.size).toBe('lg');
      expect(button.dataset.shape).toBe('pill');
      expect(button.type).toBe('button');
    }
  });

  it('renders only Cancel without a submitLabel', async () => {
    await renderActions({ submitLabel: undefined });
    const buttons = footerButtons();
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toBe('Cancel');
  });

  it('turns the submit red when destructive', async () => {
    await renderActions({ destructive: true });
    expect(footerButtons()[1].dataset.variant).toBe('destructive');
  });

  it('shows the spinner while pending and disables submit', async () => {
    await renderActions({ pending: true });
    const submit = footerButtons()[1];
    expect(submit.disabled).toBe(true);
    expect(submit.getAttribute('aria-busy')).toBe('true');
  });

  it('disables submit without a spinner when disabled', async () => {
    await renderActions({ disabled: true });
    const submit = footerButtons()[1];
    expect(submit.disabled).toBe(true);
    expect(submit.hasAttribute('aria-busy')).toBe(false);
  });

  it('pushes footerStart to the left edge from sm up', async () => {
    await renderActions({
      footerStart: <Button variant="outline">Test connection</Button>,
    });
    const start = document.querySelector('[data-slot="modal-footer-start"]')!;
    expect(start.className).toContain('sm:mr-auto');
    expect(start.textContent).toBe('Test connection');
  });

  it('passes extra props to the buttons', async () => {
    await renderActions({
      submitProps: { type: 'submit', form: 'token-form' },
      cancelProps: { 'aria-label': 'Close dialog' },
    });
    const [cancel, submit] = footerButtons();
    expect(submit.type).toBe('submit');
    expect(submit.getAttribute('form')).toBe('token-form');
    expect(cancel.getAttribute('aria-label')).toBe('Close dialog');
  });
});

describe('Modal mobile sheet', () => {
  afterEach(() => {
    media.isMobile = false;
  });

  it('takes the bottom-sheet shape and handle from ui/sheet on phones', async () => {
    media.isMobile = true;
    await render(
      <Modal
        open
        onOpenChange={() => undefined}
        title="Test retrieval"
        mobileVariant="sheet"
      >
        Body
      </Modal>,
    );
    const sheet = content();
    expect(sheet.hasAttribute('data-mobile-sheet')).toBe(true);
    const classes = sheet.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'bg-card',
        'rounded-t-2xl',
        'max-h-[90vh]',
        'pb-safe',
        'gap-3',
        'px-4',
      ]),
    );
    expect(sheet.className).not.toContain('env(');
    expect(sheet.firstElementChild!.getAttribute('data-slot')).toBe(
      'sheet-handle',
    );
  });

  it('caps the desktop dialog at 85dvh and scrolls only its body', async () => {
    await render(
      <Modal open onOpenChange={() => undefined} title="Add tool" size="xl">
        Body
      </Modal>,
    );
    const classes = content().className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'flex',
        'flex-col',
        'max-h-[85dvh]',
        'sm:max-w-4xl',
      ]),
    );
    expect(classes).not.toContain('grid');
    const body = [...content().children].find(
      (el) => el.textContent === 'Body',
    )!;
    expect(body.className).toContain('overflow-y-auto');
    expect(body.className).toContain('min-h-0');
    expect(body.className).toContain('grow');
  });

  it('keeps the centred dialog on desktop', async () => {
    await render(
      <Modal
        open
        onOpenChange={() => undefined}
        title="Test retrieval"
        mobileVariant="sheet"
      >
        Body
      </Modal>,
    );
    expect(content().hasAttribute('data-mobile-sheet')).toBe(false);
    expect(content().className).toContain('rounded-2xl');
    expect(content().querySelector('[data-slot="sheet-handle"]')).toBeNull();
  });
});
