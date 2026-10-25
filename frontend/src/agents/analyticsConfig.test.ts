import { describe, expect, it } from 'vitest';

import {
  analyticsOf,
  byName,
  configToSave,
  DEFAULT_ANALYTICS,
  descriptionMax,
  isDefaultAnalytics,
  sameAgent,
  nameTaken,
  newTopicId,
  units,
  visibleFolders,
  withAnalytics,
} from './analyticsConfig';
import type { AgentConfig, AnalyticsConfig, AnalyticsTopic } from './types';

const topic = (
  name: string,
  overlap = false,
  id = `id${name.toLowerCase().replace(/[^a-z0-9]/g, '')}0000`,
): AnalyticsTopic => ({ id, name, description: '', overlap });

describe('units', () => {
  // The server's `schema.units`: CJK x3, Cyrillic x1.2, the rest x1.
  it('counts as the server does', () => {
    expect(units('你好')).toBe(6);
    expect(units('こんにちは')).toBe(15);
    expect(units('한국')).toBe(6);
    expect(units('Docs')).toBe(4);
    expect(units('Привет')).toBeCloseTo(7.2);
    expect(units('ＡＢ')).toBe(6);
    expect(units('')).toBe(0);
  });
});

describe('newTopicId', () => {
  it('makes ids the server accepts, different each time', () => {
    const ids = new Set(Array.from({ length: 50 }, newTopicId));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(/^[a-z0-9]{8,32}$/);
  });
});

describe('defaults', () => {
  it('fills an agent saved before analytics with the defaults', () => {
    expect(analyticsOf(undefined)).toEqual(DEFAULT_ANALYTICS);
    expect(isDefaultAnalytics(undefined)).toBe(true);
    expect(isDefaultAnalytics(DEFAULT_ANALYTICS)).toBe(true);
  });

  it('knows an agent with settings of its own', () => {
    expect(isDefaultAnalytics({ ...DEFAULT_ANALYTICS, enabled: false })).toBe(
      false,
    );
    expect(isDefaultAnalytics({ ...DEFAULT_ANALYTICS, digest: true })).toBe(
      false,
    );
    expect(
      isDefaultAnalytics({
        ...DEFAULT_ANALYTICS,
        topics: [topic('Pricing', true)],
      }),
    ).toBe(false);
    expect(
      isDefaultAnalytics({ ...DEFAULT_ANALYTICS, hidden_folders: ['guides'] }),
    ).toBe(false);
  });

  it('reads a config saved under the shape before one list as the defaults, dropping its keys', () => {
    const old = {
      enabled: false,
      digest: true,
      topics: { mode: 'custom', items: [{ name: 'A', description: '' }] },
      tags: [{ id: 'a1b2c3d4', name: 'T', description: 'd' }],
    } as unknown as AnalyticsConfig;
    expect(analyticsOf(old)).toEqual({
      enabled: false,
      digest: true,
      topics: [],
      hidden_folders: [],
    });
  });

  it('gives an overlapping topic twice the description room', () => {
    expect(descriptionMax(false)).toBe(150);
    expect(descriptionMax(true)).toBe(300);
  });

  it('compares names without case or outer spaces', () => {
    expect(nameTaken(' installation ', ['Installation'])).toBe(true);
    expect(nameTaken('Install', ['Installation'])).toBe(false);
  });
});

describe('visibleFolders', () => {
  // Largest first, as the server lists them.
  const folders = ['big', 'mid', 'small', 'tiny'].map((name) => ({
    name,
    description: `Pages such as: ${name}`,
  }));
  const config = (topics: AnalyticsTopic[] = [], hidden: string[] = []) => ({
    ...DEFAULT_ANALYTICS,
    topics,
    hidden_folders: hidden,
  });
  const names = (list: { name: string }[]) => list.map((f) => f.name);

  it('shows every folder within the limit', () => {
    const view = visibleFolders(folders, config(), 15);
    expect(names(view.shown)).toEqual(['big', 'mid', 'small', 'tiny']);
    expect(view.hidden).toEqual([]);
    expect(view.cut).toEqual([]);
  });

  it('lets own topics come first and folders fill what is left, largest first', () => {
    const view = visibleFolders(
      folders,
      config([topic('Pricing'), topic('Auth'), topic('Bugs', true)]),
      4,
    );
    expect(names(view.shown)).toEqual(['big', 'mid']);
    expect(names(view.cut)).toEqual(['small', 'tiny']);
  });

  it('skips hidden folders and those an own topic is named after', () => {
    const view = visibleFolders(folders, config([topic('BIG')], ['Mid']), 15);
    expect(names(view.shown)).toEqual(['small', 'tiny']);
    expect(names(view.hidden)).toEqual(['mid']);
  });
});

describe('byName', () => {
  it('sorts ignoring case, without touching the input', () => {
    const list = [topic('beta'), topic('Alpha'), topic('gamma')];
    expect(names(byName(list))).toEqual(['Alpha', 'beta', 'gamma']);
    expect(names(list)).toEqual(['beta', 'Alpha', 'gamma']);
  });

  function names(list: { name: string }[]) {
    return list.map((item) => item.name);
  }
});

describe('configToSave', () => {
  it('saves a stored analytics block in the current shape', () => {
    const stored = {
      api_write_allowlist: ['t1:write'],
      analytics: { enabled: false, tags: [] } as unknown as AnalyticsConfig,
    };
    expect(configToSave(stored)).toEqual({
      api_write_allowlist: ['t1:write'],
      analytics: { ...DEFAULT_ANALYTICS, enabled: false },
    });
  });

  it('leaves a config without analytics as it is', () => {
    expect(configToSave(undefined)).toEqual({});
    expect(configToSave({ api_write_allowlist: [] })).toEqual({
      api_write_allowlist: [],
    });
  });
});

describe('sameAgent', () => {
  const agent: { name: string; config?: AgentConfig } = {
    name: 'Docs bot',
    config: { api_write_allowlist: [] },
  };

  it('reads a missing insights block as the defaults', () => {
    // An agent saved before insights: switching them off and on again leaves
    // nothing to save.
    expect(
      sameAgent(
        { ...agent, config: { ...agent.config, analytics: DEFAULT_ANALYTICS } },
        agent,
      ),
    ).toBe(true);
    expect(
      sameAgent(
        { name: 'Docs bot', config: { analytics: DEFAULT_ANALYTICS } },
        { name: 'Docs bot' },
      ),
    ).toBe(true);
  });

  it('tells a changed insights block or anything else apart', () => {
    const off = { ...DEFAULT_ANALYTICS, enabled: false };
    expect(
      sameAgent(
        { ...agent, config: { ...agent.config, analytics: off } },
        agent,
      ),
    ).toBe(false);
    expect(sameAgent({ ...agent, name: 'Renamed' }, agent)).toBe(false);
  });

  it('reads a cleared context limit as no limit', () => {
    // Typing a limit and clearing it again leaves nothing to save.
    expect(
      sameAgent(
        { ...agent, config: { ...agent.config, context_window_limit: null } },
        agent,
      ),
    ).toBe(true);
    expect(
      sameAgent(
        { ...agent, config: { ...agent.config, context_window_limit: 32000 } },
        agent,
      ),
    ).toBe(false);
  });
});

describe('withAnalytics', () => {
  it('replaces only analytics in the saved config', () => {
    const saved = {
      api_write_allowlist: ['t1:write'],
      analytics: { ...DEFAULT_ANALYTICS, digest: true },
    };
    const next = { ...DEFAULT_ANALYTICS, enabled: false };
    expect(withAnalytics(saved, next)).toEqual({
      api_write_allowlist: ['t1:write'],
      analytics: next,
    });
    expect(saved.analytics.digest).toBe(true);
  });

  it('starts from nothing when nothing is saved', () => {
    expect(withAnalytics(undefined, DEFAULT_ANALYTICS)).toEqual({
      analytics: DEFAULT_ANALYTICS,
    });
  });
});
