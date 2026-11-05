import { describe, expect, it } from 'vitest';

import { formatElapsed, formatRunTime, workflowStep } from './format';

const NOW = Date.parse('2026-10-13T14:20:00');

describe('formatElapsed', () => {
  it('reads as a stopwatch', () => {
    expect(formatElapsed('2026-10-13T14:19:18', NOW)).toBe('0:42');
    expect(formatElapsed('2026-10-13T14:16:48', NOW)).toBe('3:12');
    expect(formatElapsed('2026-10-13T13:15:00', NOW)).toBe('1:05:00');
  });

  it('is empty without a start', () => {
    expect(formatElapsed(null, NOW)).toBe('');
  });
});

describe('formatRunTime', () => {
  it('shows only the clock time today', () => {
    expect(formatRunTime('2026-10-13T15:00:00', NOW, 'en-GB')).toBe('15:00');
  });

  it('adds the weekday within a week', () => {
    expect(formatRunTime('2026-10-14T08:00:00', NOW, 'en-GB')).toBe(
      'Wed 08:00',
    );
  });
});

describe('workflowStep', () => {
  const current = { node_id: 'b', title: 'Draft reply', type: 'agent' };

  it('numbers the current step and fills a bar when the count is known', () => {
    expect(workflowStep({ done: 2, total: 5, current })).toEqual({
      step: 3,
      total: 5,
      title: 'Draft reply',
      percent: 40,
    });
  });

  it('has no total or bar when the workflow branches', () => {
    expect(workflowStep({ done: 2, total: null, current })).toEqual({
      step: 3,
      total: null,
      title: 'Draft reply',
      percent: null,
    });
  });

  it('is nothing before the first step starts', () => {
    expect(workflowStep(null)).toBeNull();
    expect(workflowStep({ done: 0, total: 3, current: null })).toBeNull();
  });

  it('drops a blank title', () => {
    expect(
      workflowStep({ done: 0, total: 1, current: { ...current, title: ' ' } })
        ?.title,
    ).toBeNull();
  });
});
