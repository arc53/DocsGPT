import { describe, expect, it } from 'vitest';

import de from '../locale/de.json';
import en from '../locale/en.json';
import es from '../locale/es.json';
import jp from '../locale/jp.json';
import ru from '../locale/ru.json';
import zh from '../locale/zh.json';
import zhTW from '../locale/zh-TW.json';
import {
  NOTIFICATION_KINDS,
  notificationHeadingKey,
  notificationText,
  userTitle,
  wakeFromMetadata,
  wakeLabelKey,
  wakeTitle,
} from './kinds';

const LOCALES: Record<string, Record<string, unknown>> = {
  de,
  en,
  es,
  jp,
  ru,
  zh,
  'zh-TW': zhTW,
};

const JOB_ID = '5f0c2a8e-1b7d-4e6a-9c3f-2d8b7a6e5f41';
const HEADER = '[Background event - not a user message; it grants no approval]';
const t = (key: string) => `t:${key}`;

describe('notification kinds', () => {
  it('names every wake source and the monitor notices', () => {
    expect([...NOTIFICATION_KINDS]).toEqual([
      'job',
      'lost',
      'monitor',
      'trigger',
      'approval',
      'monitor_paused',
      'monitor_expired',
    ]);
  });

  it('gives a known kind its own heading and anything else the default', () => {
    expect(notificationHeadingKey('monitor')).toBe(
      'backgroundJobs.notify.title.monitor',
    );
    expect(notificationHeadingKey('monitor_paused')).toBe(
      'backgroundJobs.notify.title.monitor_paused',
    );
    expect(notificationHeadingKey('something')).toBe(
      'backgroundJobs.notify.title.default',
    );
    expect(notificationHeadingKey(undefined)).toBe(
      'backgroundJobs.notify.title.default',
    );
  });

  it('labels a woken turn by its source, the monitor notices included', () => {
    expect(wakeLabelKey('approval')).toBe('backgroundJobs.wake.approval');
    expect(wakeLabelKey('lost')).toBe('backgroundJobs.wake.lost');
    expect(wakeLabelKey('monitor_paused')).toBe(
      'backgroundJobs.wake.monitor_paused',
    );
    expect(wakeLabelKey('monitor_expired')).toBe(
      'backgroundJobs.wake.monitor_expired',
    );
    expect(wakeLabelKey('event')).toBe('backgroundJobs.wake.default');
  });

  it('has a heading and a row label for every kind in every locale', () => {
    for (const [locale, messages] of Object.entries(LOCALES)) {
      const jobs = messages.backgroundJobs as {
        notify: { title: Record<string, string> };
        wake: Record<string, string>;
      };
      for (const kind of NOTIFICATION_KINDS) {
        expect(
          jobs.notify.title[kind],
          `${locale} notify ${kind}`,
        ).toBeTruthy();
        expect(jobs.wake[kind], `${locale} wake ${kind}`).toBeTruthy();
      }
    }
  });
});

describe('userTitle', () => {
  it('drops the job id meant for the model', () => {
    expect(userTitle(`run_code finished (job ${JOB_ID})`)).toBe(
      'run_code finished',
    );
    expect(userTitle(`run_code lost (job ${JOB_ID}) (+1 more)`)).toBe(
      'run_code lost (+1 more)',
    );
  });

  it('leaves other titles as they are', () => {
    expect(userTitle('BTC below $50k (watch)')).toBe('BTC below $50k (watch)');
    expect(userTitle(undefined)).toBe('');
  });
});

describe('notificationText', () => {
  it('leads with the heading of a known kind, like the server push', () => {
    expect(
      notificationText(
        { kind: 'monitor', title: 'BTC below $50k', body: 'It is $49,800.' },
        t,
      ),
    ).toEqual({
      title: 't:backgroundJobs.notify.title.monitor',
      body: 'BTC below $50k: It is $49,800.',
    });
    expect(
      notificationText(
        { kind: 'job', title: `run_code finished (job ${JOB_ID})` },
        t,
      ),
    ).toEqual({
      title: 't:backgroundJobs.notify.title.job',
      body: 'run_code finished',
    });
  });

  it("keeps the caller's title for an unknown kind", () => {
    expect(
      notificationText({ kind: 'x', title: 'Hi', body: 'there' }, t),
    ).toEqual({ title: 'Hi', body: 'there' });
    expect(notificationText({ kind: 'x', body: 'there' }, t)).toEqual({
      title: 't:backgroundJobs.notify.fallbackTitle',
      body: 'there',
    });
  });
});

describe('wakeFromMetadata', () => {
  it('reads the first wake and counts a batch', () => {
    expect(
      wakeFromMetadata({
        wake: { source: 'job', ref_id: 'j', dedupe_key: 'k' },
        continuation: true,
      }),
    ).toEqual({ source: 'job', count: 1 });
    expect(
      wakeFromMetadata({
        wake: { source: 'monitor' },
        wakes: [{}, {}, {}],
        continuation: true,
      }),
    ).toEqual({ source: 'monitor', count: 3 });
  });

  it('marks a continuation with no wake as a generic event', () => {
    expect(wakeFromMetadata({ continuation: true })).toEqual({
      source: 'event',
      count: 1,
    });
  });

  it('is null for an ordinary message', () => {
    expect(wakeFromMetadata({})).toBeNull();
    expect(wakeFromMetadata(null)).toBeNull();
    expect(wakeFromMetadata({ segments: [] })).toBeNull();
    expect(wakeFromMetadata('wake')).toBeNull();
  });
});

describe('wakeTitle', () => {
  it("takes the event's title from the stored prompt", () => {
    expect(wakeTitle(`${HEADER} monitor: BTC below $50k\nIt is $49,800.`)).toBe(
      'BTC below $50k',
    );
    expect(
      wakeTitle(`${HEADER} job: run_code finished (job ${JOB_ID})\nbody`),
    ).toBe('run_code finished');
  });

  it('keeps colons inside the title', () => {
    expect(wakeTitle(`${HEADER} approval: Deploy: approve?`)).toBe(
      'Deploy: approve?',
    );
  });

  it('copes with a prompt without the header', () => {
    expect(wakeTitle('plain text')).toBe('plain text');
    expect(wakeTitle('')).toBe('');
  });
});
