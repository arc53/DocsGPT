import CrawlerIcon from '../../assets/crawler.svg';
import FileUploadIcon from '../../assets/file_upload.svg';
import UrlIcon from '../../assets/url.svg';
import GithubIcon from '../../assets/github.svg';
import BookIcon from '../../assets/book-mono.svg';

export type IngestorType = 'crawler' | 'github' | 'url' | 'local_file' | 'wiki';

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

export type FieldType = 'string' | 'textarea' | 'local_file_picker';

export interface FormField {
  name: string;
  /** English fallback; the form shows `t(labelKey)` when one is set. */
  label: string;
  labelKey?: string;
  type: FieldType;
  required?: boolean;
}

export interface IngestorSchema {
  key: IngestorType;
  label: string;
  icon: string;
  heading: string;
  fields: FormField[];
}

/**
 * Add knowledge tiles: the source types that need no account. Services
 * that sync into Knowledge are connected through the connect wizard.
 */
export const UPLOAD_AND_WEB_INGESTORS: IngestorType[] = [
  'local_file',
  'url',
  'crawler',
  'github',
  'wiki',
];

export const IngestorFormSchemas: IngestorSchema[] = [
  {
    key: 'local_file',
    label: 'Upload File',
    icon: FileUploadIcon,
    heading: 'Upload new document',
    fields: [
      {
        name: 'files',
        label: 'Select files',
        type: 'local_file_picker',
        required: true,
      },
    ],
  },
  {
    key: 'crawler',
    label: 'Crawler',
    icon: CrawlerIcon,
    heading: 'Add content with Web Crawler',
    fields: [
      {
        name: 'url',
        label: 'URL',
        labelKey: 'modals.uploadDoc.fields.url',
        type: 'string',
        required: true,
      },
    ],
  },
  {
    key: 'url',
    label: 'Link',
    icon: UrlIcon,
    heading: 'Add content from URL',
    fields: [
      {
        name: 'url',
        label: 'URL',
        labelKey: 'modals.uploadDoc.fields.url',
        type: 'string',
        required: true,
      },
    ],
  },
  {
    key: 'github',
    label: 'GitHub',
    icon: GithubIcon,
    heading: 'Add content from GitHub',
    fields: [
      {
        name: 'repo_url',
        label: 'Repository URL',
        labelKey: 'modals.uploadDoc.repoUrl',
        type: 'string',
        required: true,
      },
    ],
  },
  {
    key: 'wiki',
    label: 'New wiki',
    icon: BookIcon,
    heading: 'Create a living wiki',
    fields: [
      {
        name: 'initial_content',
        label: 'Initial content (optional)',
        labelKey: 'modals.uploadDoc.fields.initialContent',
        type: 'textarea',
        required: false,
      },
    ],
  },
];

export const IngestorDefaultConfigs: Record<
  IngestorType,
  Omit<IngestorConfig, 'type'>
> = {
  crawler: { name: '', config: { url: '' } },
  url: { name: '', config: { url: '' } },
  github: { name: '', config: { repo_url: '' } },
  local_file: { name: '', config: { files: [] } },
  wiki: {
    name: '',
    config: {
      initial_content: '',
    },
  },
};

export interface IngestorOption {
  label: string;
  value: IngestorType;
  icon: string;
  heading: string;
}

export const getIngestorSchema = (
  key: IngestorType,
): IngestorSchema | undefined => {
  return IngestorFormSchemas.find((schema) => schema.key === key);
};
