import { describe, expect, it } from 'vitest';

import type { Connection, ConnectorDefinition } from '../connectors/types';
import {
  answerableServices,
  buildHeroSuggestions,
  type HeroService,
  type HeroSuggestionInput,
} from './suggestions';

const NOW = Date.parse('2026-11-01T12:00:00Z');
const daysAgo = (days: number) =>
  new Date(NOW - days * 24 * 60 * 60 * 1000).toISOString();

const contracts = { id: 'src-1', name: 'Carrier Contracts 2026' };
const handbook = { id: 'src-2', name: 'Vendor Policy Handbook' };
const notion: HeroService = {
  key: 'notion',
  name: 'Notion',
  category: 'knowledge',
  icon: 'notion',
};
const drive: HeroService = {
  key: 'google_drive',
  name: 'Google Drive',
  category: 'files',
  icon: 'google_drive',
};
const linear: HeroService = {
  key: 'linear',
  name: 'Linear',
  category: 'projects',
  icon: 'linear',
};
const qbrChat = {
  id: 'c-1',
  name: 'Halvorsen QBR prep',
  agent_id: null,
  date: daysAgo(1),
};

const input = (
  overrides: Partial<HeroSuggestionInput> = {},
): HeroSuggestionInput => ({
  selectedSources: [],
  hasSources: false,
  services: [],
  conversations: [],
  hasAgents: false,
  offerConnect: false,
  now: NOW,
  ...overrides,
});

const kinds = (rows: ReturnType<typeof buildHeroSuggestions>) =>
  rows.map((row) => row.kind);

describe('buildHeroSuggestions', () => {
  it('offers setup actions on a fresh install', () => {
    expect(kinds(buildHeroSuggestions(input({ offerConnect: true })))).toEqual([
      'addKnowledge',
      'connect',
      'createAgent',
    ]);
  });

  it('leaves out the setup steps already done', () => {
    expect(
      kinds(buildHeroSuggestions(input({ hasSources: true, hasAgents: true }))),
    ).toEqual([]);
    expect(
      kinds(
        buildHeroSuggestions(input({ hasSources: true, offerConnect: true })),
      ),
    ).toEqual(['connect', 'createAgent']);
  });

  it('summarizes and compares the selected sources (2a)', () => {
    const rows = buildHeroSuggestions(
      input({
        selectedSources: [contracts, handbook],
        hasSources: true,
        conversations: [qbrChat],
        offerConnect: true,
        hasAgents: true,
      }),
    );
    expect(rows).toEqual([
      { kind: 'summarize', source: contracts },
      { kind: 'compare', first: contracts, second: handbook },
      { kind: 'continue', chat: { id: 'c-1', name: 'Halvorsen QBR prep' } },
      { kind: 'connect' },
    ]);
  });

  it('asks about connected services when no source is selected (2b)', () => {
    const rows = buildHeroSuggestions(
      input({
        hasSources: true,
        services: [notion, drive, linear],
        conversations: [qbrChat],
        hasAgents: true,
      }),
    );
    expect(rows).toEqual([
      { kind: 'service', service: notion },
      { kind: 'service', service: drive },
      { kind: 'continue', chat: { id: 'c-1', name: 'Halvorsen QBR prep' } },
    ]);
  });

  it('continues the latest chat and suggests adding knowledge (2d)', () => {
    const older = {
      ...qbrChat,
      id: 'c-0',
      name: 'Q3 rate review',
      date: daysAgo(2),
    };
    expect(
      buildHeroSuggestions(
        input({ conversations: [older, qbrChat], offerConnect: true }),
      ),
    ).toEqual([
      { kind: 'continue', chat: { id: 'c-1', name: 'Halvorsen QBR prep' } },
      { kind: 'addKnowledge' },
    ]);
  });

  it('keeps at most three content rows and one action', () => {
    const rows = buildHeroSuggestions(
      input({
        selectedSources: [contracts, handbook],
        hasSources: true,
        services: [notion, drive],
        conversations: [qbrChat],
        offerConnect: true,
      }),
    );
    expect(kinds(rows)).toEqual(['summarize', 'compare', 'service', 'connect']);
  });

  it('skips sources still processing or failed', () => {
    const rows = buildHeroSuggestions(
      input({
        selectedSources: [
          { ...contracts, ingestStatus: 'processing' },
          handbook,
          { id: 'src-3', name: 'Broken', ingestStatus: 'failed' },
        ],
        hasSources: true,
        hasAgents: true,
      }),
    );
    expect(rows).toEqual([{ kind: 'summarize', source: handbook }]);
  });

  it('continues only a recent, named chat without an agent', () => {
    const conversations = [
      { id: 'a', name: 'Agent chat', agent_id: 'agent-1', date: daysAgo(0) },
      { id: 'b', name: '   ', agent_id: null, date: daysAgo(0) },
      { id: 'c', name: 'Stale chat', agent_id: null, date: daysAgo(8) },
      { id: 'd', name: 'Undated chat', agent_id: null },
    ];
    expect(
      kinds(
        buildHeroSuggestions(
          input({ conversations, hasSources: true, hasAgents: true }),
        ),
      ),
    ).toEqual([]);
  });
});

describe('answerableServices', () => {
  const definition = (
    key: string,
    overrides: Partial<ConnectorDefinition> = {},
  ): ConnectorDefinition =>
    ({
      key,
      name: key,
      icon: key,
      category: 'knowledge',
      capabilities: ['read'],
      publisher: 'built_in',
      ...overrides,
    }) as ConnectorDefinition;
  const connection = (
    id: string,
    connectorKey: string,
    overrides: Partial<Connection> = {},
  ): Connection =>
    ({
      id,
      connector_key: connectorKey,
      status: 'connected',
      last_used_at: null,
      ...overrides,
    }) as Connection;
  const tool = (connectionId: string, inChat = true) => ({
    connection_id: connectionId,
    in_chat: inChat,
    status: inChat,
  });
  const nameOf = (def: ConnectorDefinition) => def.name.toUpperCase();

  it('lists services with a tool on in this chat, once each', () => {
    const services = answerableServices({
      catalog: [
        definition('notion'),
        definition('google_drive', { category: 'files' }),
      ],
      connections: [
        connection('n1', 'notion'),
        connection('n2', 'notion'),
        connection('g1', 'google_drive', { last_used_at: daysAgo(0) }),
      ],
      tools: [tool('n1'), tool('n2'), tool('g1')],
      nameOf,
    });
    expect(services).toEqual([
      {
        key: 'google_drive',
        name: 'GOOGLE_DRIVE',
        category: 'files',
        icon: 'google_drive',
      },
      { key: 'notion', name: 'NOTION', category: 'knowledge', icon: 'notion' },
    ]);
  });

  it('leaves out services it could not answer about', () => {
    const services = answerableServices({
      catalog: [
        definition('notion'),
        definition('slack_bot', {
          category: 'messaging',
          capabilities: ['write'],
        }),
        definition('brave', { category: 'search' }),
        definition('my_mcp', { publisher: 'custom' }),
        definition('github', { category: 'dev' }),
      ],
      connections: [
        connection('n1', 'notion', { status: 'reconnect_needed' }),
        connection('s1', 'slack_bot'),
        connection('b1', 'brave'),
        connection('m1', 'my_mcp'),
        connection('g1', 'github'),
        connection('x1', 'unknown'),
      ],
      tools: [
        tool('n1'),
        tool('s1'),
        tool('b1'),
        tool('m1'),
        tool('g1', false),
        tool('x1'),
      ],
      nameOf,
    });
    expect(services).toEqual([]);
  });
});
