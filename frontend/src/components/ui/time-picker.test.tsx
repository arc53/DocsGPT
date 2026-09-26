import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { TimePicker } from './time-picker';

function render(): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(
    <TimePicker value="09:30" onChange={() => undefined} ariaLabel="Run at" />,
  );
  return host;
}

describe('TimePicker', () => {
  it('marks its group with data-slot', () => {
    const group = render().querySelector('[data-slot="time-picker"]')!;
    expect(group.getAttribute('role')).toBe('group');
    expect(group.getAttribute('aria-label')).toBe('Run at');
  });

  it('uses the default 36px SelectTrigger at a 68px scale width', () => {
    const triggers = Array.from(
      render().querySelectorAll('[data-slot="select-trigger"]'),
    );
    expect(triggers).toHaveLength(2);
    for (const trigger of triggers) {
      expect(trigger.getAttribute('data-size')).toBe('default');
      const classes = trigger.getAttribute('class')!.split(' ');
      expect(classes).toContain('h-9');
      expect(classes).toContain('w-17');
      expect(classes).not.toContain('w-[4.25rem]');
    }
  });
});
