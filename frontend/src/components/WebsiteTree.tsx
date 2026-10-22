import { ExternalLink, Globe } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';

import { formatCount, formatRelative } from '../utils/dateTimeUtils';
import type { LinkedChunk } from './chunkUtils';
import TreeBrowser from './tree/TreeBrowser';
import type { FileNode, RowMenuContext } from './tree/types';
import { pageAddress } from './tree/pages';
import { Button } from './ui/button';
import type { MenuOption } from './ui/dropdown-menu';

interface WebsiteTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control (Test retrieval). */
  headerAction?: React.ReactNode;
  /** The hosts the source fetches from (the sources list's `website.hosts`). */
  hosts: string[];
  /** `sources.sync_frequency`; never (or empty) reads "Not synced". */
  syncFrequency?: string;
  /** When the source was last ingested or synced. */
  syncedAt?: string;
  canEdit?: boolean;
  initialPath?: string;
  linkedChunk?: LinkedChunk;
}

/**
 * A Website source in Knowledge: its pages by title, each with its address,
 * and a header line that says where the source comes from and how it stays
 * current. An open page's header links to the live page.
 */
const WebsiteTree: React.FC<WebsiteTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
  headerAction,
  hosts,
  syncFrequency,
  syncedAt,
  canEdit = true,
  initialPath,
  linkedChunk,
}) => {
  const { t } = useTranslation();
  const tr = (key: string, options?: Record<string, unknown>) =>
    t(`settings.sources.website.${key}`, options);

  const openLink = (url: string, label: string) => (
    <Button variant="link" size="inline" asChild>
      <a href={url} target="_blank" rel="noopener noreferrer">
        {label}
        <ExternalLink />
      </a>
    </Button>
  );

  const syncLine =
    syncFrequency && syncFrequency !== 'never'
      ? tr('synced', {
          frequency: t(`settings.sources.syncFrequency.${syncFrequency}`),
          when: formatRelative(syncedAt) ?? '',
        })
      : tr('notSynced');

  const renderByline = ({
    openFile,
    files,
    tokens,
  }: {
    openFile: FileNode | null;
    files: number;
    tokens: number;
  }) => {
    const parts: React.ReactNode[] = [];
    if (openFile && typeof openFile.url === 'string') {
      parts.push(openLink(openFile.url, pageAddress(openFile.url)));
      const when =
        typeof openFile.fetched_at === 'string'
          ? formatRelative(openFile.fetched_at)
          : null;
      if (when) parts.push(tr('fetchedAt', { when }));
    } else {
      if (hosts.length === 1) {
        parts.push(
          <span className="inline-flex items-center gap-1.5">
            <Globe className="size-4" aria-hidden="true" />
            {openLink(`https://${hosts[0]}`, hosts[0])}
          </span>,
        );
      } else if (hosts.length > 1) {
        parts.push(tr('sites', { count: hosts.length }));
      }
      parts.push(
        tr('pagesByline', {
          count: files,
          pages: formatCount(files),
          tokens: formatCount(tokens),
        }),
      );
      parts.push(syncLine);
    }
    return (
      <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
        {parts.map((part, index) => (
          <span key={index}>{part}</span>
        ))}
      </span>
    );
  };

  const getRowMenuOptions = ({
    defaultViewOption,
    node,
  }: RowMenuContext): MenuOption[] => {
    const url = typeof node?.url === 'string' ? node.url : null;
    if (!url) return [defaultViewOption];
    return [
      defaultViewOption,
      {
        icon: ExternalLink,
        label: tr('openPage'),
        onClick: () => window.open(url, '_blank', 'noopener,noreferrer'),
      },
    ];
  };

  return (
    <TreeBrowser
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
      columnOrder="size-first"
      variant="pages"
      renderByline={renderByline}
      topRightAction={headerAction}
      getRowMenuOptions={getRowMenuOptions}
      canEdit={canEdit}
      initialPath={initialPath}
      linkedChunk={linkedChunk}
    />
  );
};

export default WebsiteTree;
