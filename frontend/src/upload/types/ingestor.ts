export interface BaseIngestorConfig {
  [key: string]: string | number | boolean | undefined;
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

export interface GoogleDriveIngestorConfig extends BaseIngestorConfig {
  folder_id?: string;
  file_ids?: string;
  recursive?: boolean;
  token_info?: any;
}

export type IngestorType = 'crawler' | 'github' | 'reddit' | 'url' | 'google_drive';

export interface IngestorConfig {
  type: IngestorType;
  name: string;
  config:
    | RedditIngestorConfig
    | GithubIngestorConfig
    | CrawlerIngestorConfig
    | UrlIngestorConfig
    | GoogleDriveIngestorConfig;
}

export type IngestorFormData = {
  name: string;
  user: string;
  source: IngestorType;
  data: string;
};

export type FieldType = 'string' | 'number' | 'enum' | 'boolean';

export interface FormField {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  advanced?: boolean;
  options?: { label: string; value: string }[];
}

export const IngestorFormSchemas: Record<IngestorType, FormField[]> = {
  crawler: [
    {
      name: 'url',
      label: 'URL',
      type: 'string',
      required: true,
    },
  ],
  url: [
    {
      name: 'url',
      label: 'URL',
      type: 'string',
      required: true,
    },
  ],
  reddit: [
    {
      name: 'client_id',
      label: 'Client ID',
      type: 'string',
      required: true,
    },
    {
      name: 'client_secret',
      label: 'Client Secret',
      type: 'string',
      required: true,
    },
    {
      name: 'user_agent',
      label: 'User Agent',
      type: 'string',
      required: true,
    },
    {
      name: 'search_queries',
      label: 'Search Queries',
      type: 'string',
      required: true,
    },
    {
      name: 'number_posts',
      label: 'Number of Posts',
      type: 'number',
      required: true,
    },
  ],
  github: [
    {
      name: 'repo_url',
      label: 'Repository URL',
      type: 'string',
      required: true,
    },
  ],
  google_drive: [
    {
      name: 'recursive',
      label: 'Include subfolders',
      type: 'boolean',
      required: false,
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
  google_drive: {
    name: '',
    config: {
      folder_id: '',
      file_ids: '',
      recursive: true,
    } as GoogleDriveIngestorConfig,
  },
};
