import CrawlerIcon from '../../assets/crawler.svg';
import FileUploadIcon from '../../assets/file_upload.svg';
import UrlIcon from '../../assets/url.svg';
import GithubIcon from '../../assets/github.svg';
import RedditIcon from '../../assets/reddit.svg';
import DriveIcon from '../../assets/drive.svg';

export type IngestorType = 'crawler' | 'github' | 'reddit' | 'url' | 'google_drive' | 'local_file';

export interface IngestorConfig {
  type: IngestorType | null;
  name: string;
  config: Record<string, string | number | boolean | File[]>;
}

export type IngestorFormData = {
  name: string;
  user: string;
  source: IngestorType;
  data: string;
};

export type FieldType = 'string' | 'number' | 'enum' | 'boolean' | 'local_file_picker' | 'remote_file_picker' | 'google_drive_picker';

export interface FormField {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  advanced?: boolean;
  options?: { label: string; value: string }[];
}

export interface IngestorSchema {
  key: IngestorType;
  label: string;
  icon: string;
  heading: string;
  validate?: () => boolean;
  fields: FormField[];
}

export const IngestorFormSchemas: IngestorSchema[] = [
  {
    key: 'local_file',
    label: 'Upload File',
    icon: FileUploadIcon,
    heading: 'Upload new document',
    fields: [
      { name: 'files', label: 'Select files', type: 'local_file_picker', required: true },
    ]
  },
  {
    key: 'crawler',
    label: 'Crawler',
    icon: CrawlerIcon,
    heading: 'Add content with Web Crawler',
    fields: [{ name: 'url', label: 'URL', type: 'string', required: true }]
  },
  {
    key: 'url',
    label: 'Link',
    icon: UrlIcon,
    heading: 'Add content from URL',
    fields: [{ name: 'url', label: 'URL', type: 'string', required: true }]
  },
  {
    key: 'github',
    label: 'GitHub',
    icon: GithubIcon,
    heading: 'Add content from GitHub',
    fields: [{ name: 'repo_url', label: 'Repository URL', type: 'string', required: true }]
  },
  {
    key: 'reddit',
    label: 'Reddit',
    icon: RedditIcon,
    heading: 'Add content from Reddit',
    fields: [
      { name: 'client_id', label: 'Client ID', type: 'string', required: true },
      { name: 'client_secret', label: 'Client Secret', type: 'string', required: true },
      { name: 'user_agent', label: 'User Agent', type: 'string', required: true },
      { name: 'search_queries', label: 'Search Queries', type: 'string', required: true },
      { name: 'number_posts', label: 'Number of Posts', type: 'number', required: true },
    ]
  },
  {
    key: 'google_drive',
    label: 'Google Drive',
    icon: DriveIcon,
    heading: 'Upload from Google Drive',
    validate: () => {
      const googleApiKey = import.meta.env.VITE_GOOGLE_API_KEY;
      const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
      return !!(googleApiKey && googleClientId);
    },
    fields: [
      {
        name: 'files',
        label: 'Select Files from Google Drive',
        type: 'google_drive_picker',
        required: true,
      }
    ]
  },
];

export const IngestorDefaultConfigs: Record<IngestorType, Omit<IngestorConfig, 'type'>> = {
  crawler: { name: '', config: { url: '' } },
  url: { name: '', config: { url: '' } },
  reddit: {
    name: '',
    config: {
      client_id: '',
      client_secret: '',
      user_agent: '',
      search_queries: '',
      number_posts: 10
    }
  },
  github: { name: '', config: { repo_url: '' } },
  google_drive: {
    name: '',
    config: {
      file_ids: '',
      folder_ids: '',
      recursive: true
    }
  },
  local_file: { name: '', config: { files: [] } },
};

export interface IngestorOption {
  label: string;
  value: IngestorType;
  icon: string;
  heading: string;
}

export const getIngestorSchema = (key: IngestorType): IngestorSchema | undefined => {
  return IngestorFormSchemas.find(schema => schema.key === key);
};


