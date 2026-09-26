import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import '../../locale/i18n';

import SchedulerToolCallCard, {
  extractToolError,
  type SchedulerToolCallCardProps,
} from './SchedulerToolCallCard';

vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: () => null,
}));

const render = (props: SchedulerToolCallCardProps) =>
  renderToStaticMarkup(createElement(SchedulerToolCallCard, props));

// Regression for the iter-6 issue where ``cancel_scheduled_task`` returning
// a plain ``"Error: …"`` string still rendered "Scheduled task cancelled."
// The fix is to extract the error message so the card can branch on it.
describe('extractToolError', () => {
  it('returns the message for an Error: prefixed string', () => {
    expect(
      extractToolError('Error: scheduled task not found or already terminal.'),
    ).toBe('scheduled task not found or already terminal.');
  });

  it('trims leading whitespace before the prefix', () => {
    expect(extractToolError('  Error: foo  ')).toBe('foo');
  });

  it('returns null for JSON success payloads', () => {
    expect(
      extractToolError(JSON.stringify({ task_id: 'x', status: 'cancelled' })),
    ).toBeNull();
  });

  it('returns null for plain non-error strings', () => {
    expect(extractToolError('done')).toBeNull();
  });

  it('returns null for object results', () => {
    expect(extractToolError({ task_id: 'x' })).toBeNull();
  });

  it('returns null for undefined / null', () => {
    expect(extractToolError(undefined)).toBeNull();
    expect(extractToolError(null)).toBeNull();
  });
});

describe('SchedulerToolCallCard', () => {
  const scheduled = {
    task_id: 't1',
    resolved_run_at: '2026-09-27T09:00:00Z',
    instruction: 'Send the weekly report',
  };

  it('renders a scheduled task on a Card with an icon, time and cancel pill', () => {
    const html = render({ actionName: 'schedule_task', result: scheduled });
    expect(html).toContain('data-slot="card"');
    expect(html).not.toContain('rounded-2xl border p-4');
    expect(html).toContain('lucide-calendar-clock');
    expect(html).toContain('>Scheduled task<');
    expect(html).not.toContain('⏰');
    expect(html).toContain('text-muted-foreground text-xs');
    // Instruction: muted, indented under the title, no quotes or italic.
    expect(html).toContain('Send the weekly report');
    expect(html).not.toContain('“');
    expect(html).not.toContain('italic');
    expect(html).toContain('pl-7');
    expect(html).toContain('data-variant="destructive-outline"');
    expect(html).toContain('>Cancel<');
    expect(html).not.toContain('mt-2');
  });

  it('shows a spinner, not the calendar icon, while pending', () => {
    const html = render({
      actionName: 'schedule_task',
      result: scheduled,
      status: 'pending',
    });
    expect(html).toContain('data-slot="spinner"');
    expect(html).not.toContain('lucide-calendar-clock');
    expect(html).toContain('Scheduling…');
  });

  it('puts the scheduling error on its own line under a title-only heading', () => {
    const html = render({
      actionName: 'schedule_task',
      result: { error: 'bad time' },
    });
    expect(html).toContain('lucide-circle-alert');
    expect(html).toContain('>Scheduling failed<');
    expect(html).toContain('>bad time<');
  });

  it('puts the cancel error on its own line under a title-only heading', () => {
    const html = render({
      actionName: 'cancel_scheduled_task',
      result: 'Error: not found',
    });
    expect(html).toContain('lucide-circle-alert');
    expect(html).toContain('>Cancel failed<');
    expect(html).toContain('>not found<');
  });

  it('renders a successful cancel with the cancelled calendar icon', () => {
    const html = render({
      actionName: 'cancel_scheduled_task',
      result: { task_id: 't1', status: 'cancelled' },
    });
    expect(html).toContain('lucide-calendar-x-2');
    expect(html).toContain('Scheduled task cancelled.');
  });

  it('lists pending tasks on a Card', () => {
    const html = render({
      actionName: 'list_scheduled_tasks',
      result: { tasks: [scheduled] },
    });
    expect(html).toContain('data-slot="card"');
    expect(html).toContain('1 pending scheduled task');
    expect(html).toContain('Send the weekly report');
    expect(html).not.toContain('mt-2');
  });
});
