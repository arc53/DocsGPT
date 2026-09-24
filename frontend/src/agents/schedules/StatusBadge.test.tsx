import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import ScheduleStatusBadge, {
  formatStatusLabel,
  getStatusVariant,
  type ScheduleStatusBadgeStatus,
} from './StatusBadge';

type Case = {
  status: ScheduleStatusBadgeStatus;
  label: string;
  variant: string;
};

const CASES: Case[] = [
  // Schedule statuses
  {
    status: 'active',
    label: 'Active',
    variant: 'success',
  },
  {
    status: 'paused',
    label: 'Paused',
    variant: 'warning',
  },
  {
    status: 'completed',
    label: 'Completed',
    variant: 'success',
  },
  {
    status: 'cancelled',
    label: 'Cancelled',
    variant: 'neutral',
  },
  // Run statuses
  {
    status: 'success',
    label: 'Success',
    variant: 'success',
  },
  {
    status: 'failed',
    label: 'Failed',
    variant: 'destructive',
  },
  {
    status: 'skipped',
    label: 'Skipped',
    variant: 'warning',
  },
  {
    status: 'running',
    label: 'Running',
    variant: 'info',
  },
  {
    status: 'pending',
    label: 'Pending',
    variant: 'neutral',
  },
  {
    status: 'timeout',
    label: 'Timeout',
    variant: 'destructive',
  },
];

describe('ScheduleStatusBadge', () => {
  it.each(CASES)(
    'renders $status with label "$label" as a $variant badge',
    ({ status, label, variant }) => {
      const html = renderToStaticMarkup(
        <ScheduleStatusBadge status={status} />,
      );
      expect(html).toContain(label);
      expect(html).toContain(`data-status="${status}"`);
      expect(html).toContain('data-slot="badge"');
      expect(html).toContain(`data-variant="${variant}"`);
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

describe('getStatusVariant', () => {
  it('returns neutral for an unknown status', () => {
    // @ts-expect-error -- exercising the runtime fallback for unknown values
    expect(getStatusVariant('unknown')).toBe('neutral');
  });
});
