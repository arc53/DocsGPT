export interface BaseIngestorConfig {
  name: string;
}

export interface RedditIngestorConfig extends BaseIngestorConfig {
  client_id: string;
  client_secret: string;
  user_agent: string;
  search_queries: string[];
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
    | UrlIngestorConfig
    | string;
}

export type IngestorFormData = {
  name: string;
  user: string;
  source: IngestorType;
  data: string;
};
