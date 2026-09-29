import { BookMarked, Check, ExternalLink, Lock } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import connectorsService from '../api/services/connectorsService';
import { useConnectorAuth } from '../components/ConnectorAuth';
import SearchInput from '../components/SearchInput';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
import { formatDateTime } from '../utils/dateTimeUtils';
import type { GitHubRepository } from './types';

type LoadError = 'reconnect' | 'failed' | null;

/**
 * Pick one repository a GitHub connection can read. A token lists what it
 * was granted; a GitHub App sign-in lists its installations' repositories,
 * and more are chosen on GitHub (the app's installation page), after which
 * the list reloads.
 */
export default function RepoPicker({
  connectionId,
  token,
  value,
  onChange,
}: {
  connectionId: string;
  token: string | null;
  /** The picked repository's `owner/name`. */
  value: string | null;
  onChange: (fullName: string) => void;
}) {
  const { t } = useTranslation();
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [installUrl, setInstallUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [query, setQuery] = useState('');
  // Only the latest load may land: a reload after choosing repositories
  // must not be overwritten by a slower earlier one.
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const data = await connectorsService.repositories(connectionId, token);
      if (request !== requestRef.current) return;
      if (!data?.success) {
        setError(data?.code === 'reconnect' ? 'reconnect' : 'failed');
        return;
      }
      setRepositories(data.repositories ?? []);
      setInstallUrl(data.install_url ?? null);
    } catch {
      if (request === requestRef.current) setError('failed');
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }, [connectionId, token]);

  useEffect(() => {
    load();
  }, [load]);

  // The popup reports success when the app asks for authorization during
  // installation; otherwise the user closes it. Reload either way.
  const chooseRepositories = useConnectorAuth({
    provider: 'github',
    connectionId,
    install: true,
    onSuccess: () => load(),
    onError: () => load(),
  });

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return repositories;
    return repositories.filter(
      (repo) =>
        repo.full_name.toLowerCase().includes(needle) ||
        repo.description.toLowerCase().includes(needle),
    );
  }, [repositories, query]);

  const chooseButton = installUrl ? (
    <Button
      type="button"
      variant="link"
      size="inline"
      className="w-fit"
      onClick={chooseRepositories}
    >
      <ExternalLink />
      {t('settings.connectors.github.chooseRepositories')}
    </Button>
  ) : null;

  if (loading && repositories.length === 0)
    return <LoadingState fill="block" />;
  if (error) {
    return (
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title={
          error === 'reconnect'
            ? t('settings.connectors.detail.expired')
            : t('settings.connectors.github.loadFailed')
        }
        action={
          error === 'failed' ? (
            <Button variant="outline" size="sm" shape="pill" onClick={load}>
              {t('retry')}
            </Button>
          ) : undefined
        }
      />
    );
  }
  if (repositories.length === 0) {
    return (
      <EmptyState
        size="xs"
        illustration="none"
        title={
          installUrl
            ? t('settings.connectors.github.noAppRepositories')
            : t('settings.connectors.github.noTokenRepositories')
        }
        action={chooseButton ?? undefined}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <SearchInput
        label={t('settings.connectors.github.searchRepositories')}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {visible.length === 0 ? (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.connectors.noMatches')}
        />
      ) : (
        <Card
          variant="subtle"
          padding="none"
          className="max-h-80 overflow-y-auto"
        >
          <div
            role="radiogroup"
            aria-label={t('settings.connectors.github.repositories')}
          >
            <ListRows>
              {visible.map((repo) => {
                const picked = repo.full_name === value;
                return (
                  <ListRow
                    key={repo.full_name}
                    interactive
                    asChild
                    leading={
                      <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
                        {repo.private ? (
                          <Lock className="size-4" aria-hidden />
                        ) : (
                          <BookMarked className="size-4" aria-hidden />
                        )}
                      </span>
                    }
                    title={repo.full_name}
                    description={
                      repo.description ||
                      (repo.updated_at
                        ? t('settings.connectors.github.updated', {
                            date: formatDateTime(repo.updated_at),
                            interpolation: { escapeValue: false },
                          })
                        : undefined)
                    }
                    trailing={
                      picked ? (
                        <Check
                          className="text-primary size-4 shrink-0"
                          aria-hidden
                        />
                      ) : undefined
                    }
                  >
                    <button
                      type="button"
                      role="radio"
                      aria-checked={picked}
                      onClick={() => onChange(repo.full_name)}
                    />
                  </ListRow>
                );
              })}
            </ListRows>
          </div>
        </Card>
      )}
      {chooseButton}
    </div>
  );
}
