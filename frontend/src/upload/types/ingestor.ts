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

export const IngestorFormSchemas: Record<IngestorType, FormField[]> = {
  crawler: [{ name: 'url', label: 'URL', type: 'string', required: true }],
  url: [{ name: 'url', label: 'URL', type: 'string', required: true }],
  reddit: [
    { name: 'client_id', label: 'Client ID', type: 'string', required: true },
    { name: 'client_secret', label: 'Client Secret', type: 'string', required: true },
    { name: 'user_agent', label: 'User Agent', type: 'string', required: true },
    { name: 'search_queries', label: 'Search Queries', type: 'string', required: true },
    { name: 'number_posts', label: 'Number of Posts', type: 'number', required: true },
  ],
  github: [{ name: 'repo_url', label: 'Repository URL', type: 'string', required: true }],
  google_drive: [
    {
      name: 'files',
      label: 'Select Files from Google Drive',
      type: 'google_drive_picker',
      required: true,
    },
    { name: 'recursive', label: 'Include subfolders', type: 'boolean', required: false },
  ],
  local_file: [
    { name: 'files', label: 'Select files', type: 'local_file_picker', required: true },
  ],
};

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


