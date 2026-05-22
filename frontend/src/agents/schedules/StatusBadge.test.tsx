import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import ScheduleStatusBadge, {
  formatStatusLabel,
  getStatusClasses,
  type ScheduleStatusBadgeStatus,
} from './StatusBadge';

type Case = {
  status: ScheduleStatusBadgeStatus;
  label: string;
  classes: string[];
};

const CASES: Case[] = [
  // Schedule statuses
  {
    status: 'active',
    label: 'Active',
    classes: ['bg-green-100', 'text-green-700'],
  },
  {
    status: 'paused',
    label: 'Paused',
    classes: ['bg-amber-100', 'text-amber-700'],
  },
  {
    status: 'completed',
    label: 'Completed',
    classes: ['bg-blue-100', 'text-blue-700'],
  },
  {
    status: 'cancelled',
    label: 'Cancelled',
    classes: ['bg-muted', 'text-muted-foreground'],
  },
  // Run statuses
  {
    status: 'success',
    label: 'Success',
    classes: ['bg-green-100', 'text-green-700'],
  },
  {
    status: 'failed',
    label: 'Failed',
    classes: ['bg-red-100', 'text-red-700'],
  },
  {
    status: 'skipped',
    label: 'Skipped',
    classes: ['bg-amber-100', 'text-amber-700'],
  },
  {
    status: 'running',
    label: 'Running',
    classes: ['bg-blue-100', 'text-blue-700'],
  },
  {
    status: 'pending',
    label: 'Pending',
    classes: ['bg-muted', 'text-muted-foreground'],
  },
  {
    status: 'timeout',
    label: 'Timeout',
    classes: ['bg-red-100', 'text-red-700'],
  },
];

describe('ScheduleStatusBadge', () => {
  it.each(CASES)(
    'renders $status with label "$label" and the right color classes',
    ({ status, label, classes }) => {
      const html = renderToStaticMarkup(
        <ScheduleStatusBadge status={status} />,
      );
      expect(html).toContain(label);
      expect(html).toContain(`data-status="${status}"`);
      for (const cls of classes) {
        expect(html).toContain(cls);
      }
    },
  );

  it('passes through an extra className', () => {
    const html = renderToStaticMarkup(
      <ScheduleStatusBadge status="active" className="ml-2" />,
    );
    expect(html).toContain('ml-2');
  });
});

describe('formatStatusLabel', () => {
  it('capitalizes a single-word status', () => {
    expect(formatStatusLabel('active')).toBe('Active');
  });

  it('replaces underscores with spaces', () => {
    expect(formatStatusLabel('auth_expired')).toBe('Auth expired');
  });
});

describe('getStatusClasses', () => {
  it('returns muted classes for an unknown status', () => {
    // @ts-expect-error -- exercising the runtime fallback for unknown values
    expect(getStatusClasses('unknown')).toContain('text-muted-foreground');
  });
});
