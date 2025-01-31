export interface BaseIngestorConfig {
  name: string;
}

export interface RedditIngestorConfig extends BaseIngestorConfig {
  client_id: string;
  client_secret: string;
  user_agent: string;
  search_queries: string;
  number_posts: number;
}

export interface GithubIngestorConfig extends BaseIngestorConfig {
  repo_url: string;
}

export interface CrawlerIngestorConfig extends BaseIngestorConfig {
  url: string;
}

export interface UrlIngestorConfig extends BaseIngestorConfig {
  url: string;
}

export type IngestorType = 'crawler' | 'github' | 'reddit' | 'url';

export interface IngestorConfig {
  type: IngestorType;
  name: string;
  config:
    | RedditIngestorConfig
    | GithubIngestorConfig
    | CrawlerIngestorConfig
    | UrlIngestorConfig;
}

export type IngestorFormData = {
  name: string;
  user: string;
  source: IngestorType;
  data: string;
};

export type FieldType = 'string' | 'number' | 'enum' | 'boolean';

export interface FormField {
  name: keyof BaseIngestorConfig | string;
  label: string;
  type: FieldType;
  options?: { label: string; value: string }[];
}

export const IngestorFormSchemas: Record<IngestorType, FormField[]> = {
  crawler: [
    {
      name: 'url',
      label: 'URL',
      type: 'string',
    },
  ],
  url: [
    {
      name: 'url',
      label: 'URL',
      type: 'string',
    },
  ],
  reddit: [
    {
      name: 'client_id',
      label: 'Client ID',
      type: 'string',
    },
    {
      name: 'client_secret',
      label: 'Client Secret',
      type: 'string',
    },
    {
      name: 'user_agent',
      label: 'User Agent',
      type: 'string',
    },
    {
      name: 'search_queries',
      label: 'Search Queries',
      type: 'string',
    },
    {
      name: 'number_posts',
      label: 'Number of Posts',
      type: 'number',
    },
  ],
  github: [
    {
      name: 'repo_url',
      label: 'Repository URL',
      type: 'string',
    },
  ],
};

export const IngestorDefaultConfigs: Record<
  IngestorType,
  Omit<IngestorConfig, 'type'>
> = {
  crawler: {
    name: '',
    config: {
      url: '',
    } as CrawlerIngestorConfig,
  },
  url: {
    name: '',
    config: {
      url: '',
    } as UrlIngestorConfig,
  },
  reddit: {
    name: '',
    config: {
      client_id: '',
      client_secret: '',
      user_agent: '',
      search_queries: '',
      number_posts: 10,
    } as RedditIngestorConfig,
  },
  github: {
    name: '',
    config: {
      repo_url: '',
    } as GithubIngestorConfig,
  },
};
