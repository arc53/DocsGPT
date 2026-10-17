import type { Monitor } from './types';

/** A monitor as `/api/monitors` returns it, for tests. */
export const sampleMonitor = (overrides: Partial<Monitor> = {}): Monitor => ({
  monitor_id: 'm-1',
  description: 'ACMEB below $90',
  status: 'active',
  source_type: 'webpage',
  watching: 'the page https://shop.example.com',
  target: 'https://shop.example.com',
  interval: '15m',
  interval_seconds: 900,
  conversation_id: 'c-1',
  agent_id: null,
  created_at: '2026-10-05T12:00:00Z',
  expires_at: '2026-10-12T12:00:00Z',
  next_check_at: '2026-10-05T12:15:00Z',
  last_checked_at: '2026-10-05T12:00:00Z',
  last_changed_at: null,
  last_woken_at: null,
  check_count: 1,
  wake_count: 0,
  max_wakes: 1,
  wakes_left: 1,
  last_error: null,
  paused_reason: null,
  approval_required: false,
  ...overrides,
});
