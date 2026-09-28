import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import WorkflowDetailsSheet from './WorkflowDetailsSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const details = {
  name: 'Helpdesk Triage',
  description: 'Routes internal requests',
  allowPromptOverride: false,
};

describe('WorkflowDetailsSheet', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = (props: { errors?: string[]; saving?: boolean } = {}) => {
    const handlers = { onOpenChange: vi.fn(), onSave: vi.fn() };
    act(() => {
      root.render(
        <WorkflowDetailsSheet
          open
          details={details}
          currentImage=""
          saving={props.saving ?? false}
          errors={props.errors ?? []}
          {...handlers}
        />,
      );
    });
    return handlers;
  };

  const button = (name: string) =>
    Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === name,
    ) as HTMLButtonElement;

  const nameInput = () =>
    document.querySelector('input[type="text"]') as HTMLInputElement;

  const type = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('opens with the workflow details filled in', () => {
    render();
    expect(document.body.textContent).toContain(
      'agents.workflow.builder.detailsTitle',
    );
    expect(nameInput().value).toBe('Helpdesk Triage');
    expect(document.querySelector('textarea')?.value).toBe(
      'Routes internal requests',
    );
    expect(document.querySelector('[role="switch"]')).not.toBeNull();
  });

  it('keeps Save disabled until something changes, then saves the edits', () => {
    const { onSave } = render();
    const save = button('agents.form.buttons.save');
    expect(save.disabled).toBe(true);

    type(nameInput(), 'Helpdesk Router');
    expect(save.disabled).toBe(false);

    act(() => save.click());
    expect(onSave).toHaveBeenCalledWith({
      name: 'Helpdesk Router',
      description: 'Routes internal requests',
      allowPromptOverride: false,
      imageFile: null,
    });
  });

  it('closes on Cancel without saving', () => {
    const { onOpenChange, onSave } = render();
    type(nameInput(), 'Something else');
    act(() => button('agents.form.buttons.cancel').click());
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('lists save errors in an alert inside the sheet', () => {
    render({ errors: ['Workflow must have an end node'] });
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('agents.workflow.builder.unableSave');
    expect(alert?.textContent).toContain('Workflow must have an end node');
  });
});
