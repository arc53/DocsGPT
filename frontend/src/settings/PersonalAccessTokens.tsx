import { TriangleAlert } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import patService, {
  AccessTokenApiError,
  AccessTokenPolicy,
  AccessTokenScope,
  CreateAccessTokenResponse,
  PersonalAccessToken,
} from '../api/services/patService';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SkeletonLoader from '../components/SkeletonLoader';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { useDarkTheme } from '../hooks';
import AccessTokenCreatedModal from '../modals/AccessTokenCreatedModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import CreateAccessTokenModal from '../modals/CreateAccessTokenModal';
import RegenerateAccessTokenModal from '../modals/RegenerateAccessTokenModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { formatDateOnly, formatDateTime } from '../utils/dateTimeUtils';
import {
  countLiveTokens,
  expiryStatus,
  NO_ESCAPE,
  relativeTime,
  restrictionCounts,
} from './accessTokenUtils';

const VISIBLE_SCOPES = 3;

function ScopeChips({ scopes }: { scopes: string[] }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const visible = expanded ? scopes : scopes.slice(0, VISIBLE_SCOPES);
  const hidden = scopes.length - visible.length;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {visible.map((scope) => (
        <span
          key={scope}
          className="bg-muted text-foreground rounded-full px-2 py-0.5 font-mono text-xs leading-4 whitespace-nowrap"
        >
          {scope}
        </span>
      ))}
      {scopes.length > VISIBLE_SCOPES && (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
          title={expanded ? undefined : scopes.slice(VISIBLE_SCOPES).join(', ')}
          className="text-primary hover:bg-primary/10 cursor-pointer rounded-full px-2 py-0.5 text-xs leading-4 font-medium whitespace-nowrap"
        >
          {expanded
            ? t('settings.accessTokens.showLess')
            : t('settings.accessTokens.moreScopes', { count: hidden })}
        </button>
      )}
    </div>
  );
}

export default function PersonalAccessTokens() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();

  const [tokens, setTokens] = React.useState<PersonalAccessToken[]>([]);
  const [scopes, setScopes] = React.useState<AccessTokenScope[]>([]);
  const [policy, setPolicy] = React.useState<AccessTokenPolicy | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [createOpen, setCreateOpen] = React.useState(false);
  // The plaintext secret lives only here, and only until the modal closes.
  const [created, setCreated] =
    React.useState<CreateAccessTokenResponse | null>(null);
  // True while `created` holds a regenerated (not brand-new) secret.
  const [createdByRegenerate, setCreatedByRegenerate] = React.useState(false);
  const [tokenToRegenerate, setTokenToRegenerate] =
    React.useState<PersonalAccessToken | null>(null);
  const [revokeState, setRevokeState] = React.useState<ActiveState>('INACTIVE');
  const [tokenToRevoke, setTokenToRevoke] =
    React.useState<PersonalAccessToken | null>(null);

  const loadTokens = React.useCallback(
    async (showLoader: boolean) => {
      if (showLoader) setLoading(true);
      try {
        const data = await patService.list(token);
        setTokens(data.tokens ?? []);
        setScopes(data.scopes ?? []);
        setPolicy(data.policy ?? null);
        setError(null);
      } catch (err) {
        console.error('Failed to load access tokens:', err);
        setError(t('settings.accessTokens.loadError'));
      } finally {
        setLoading(false);
      }
    },
    [token, t],
  );

  React.useEffect(() => {
    loadTokens(true);
  }, [loadTokens]);

  const handleRegenerated = (response: CreateAccessTokenResponse) => {
    const updated = response.personal_access_token;
    setTokenToRegenerate(null);
    setCreatedByRegenerate(true);
    setCreated(response);
    setTokens((prev) =>
      prev.map((item) => (item.id === updated.id ? updated : item)),
    );
    setError(null);
  };

  const handleCreated = (response: CreateAccessTokenResponse) => {
    setCreateOpen(false);
    setCreatedByRegenerate(false);
    setCreated(response);
    setTokens((prev) => [response.personal_access_token, ...prev]);
  };

  const requestRevoke = (item: PersonalAccessToken) => {
    setTokenToRevoke(item);
    setRevokeState('ACTIVE');
  };

  const confirmRevoke = async () => {
    if (!tokenToRevoke) return;
    const target = tokenToRevoke;
    try {
      await patService.revoke(target.id, token);
      setTokens((prev) => prev.filter((item) => item.id !== target.id));
      setError(null);
    } catch (err) {
      if (err instanceof AccessTokenApiError && err.status === 404) {
        // Already revoked elsewhere (another tab, an admin): it is gone, so
        // drop the stale row instead of reporting a failure.
        setTokens((prev) => prev.filter((item) => item.id !== target.id));
        setError(null);
        return;
      }
      console.error('Failed to revoke access token:', err);
      setError(
        (err instanceof Error && err.message) ||
          t('settings.accessTokens.revokeError'),
      );
    } finally {
      setTokenToRevoke(null);
    }
  };

  const limitReached =
    !!policy && countLiveTokens(tokens) >= policy.max_per_user;

  const renderRestrictions = (item: PersonalAccessToken) => {
    const counts = restrictionCounts(item.resource_filter);
    if (counts.length === 0) return t('settings.accessTokens.allResources');
    return counts
      .map(({ family, count }) =>
        t(`settings.accessTokens.restrictionCount.${family}`, {
          count,
          defaultValue: `${count} ${family}`,
        }),
      )
      .join(', ');
  };

  const renderLastUsed = (item: PersonalAccessToken) => {
    const relative = relativeTime(item.last_used_at);
    if (!relative || !item.last_used_at) {
      return t('settings.accessTokens.never');
    }
    const label =
      relative.unit === 'date'
        ? formatDateOnly(item.last_used_at)
        : relative.unit === 'now'
          ? t('settings.accessTokens.relative.now')
          : t(`settings.accessTokens.relative.${relative.unit}`, {
              count: relative.count,
            });
    const details = [formatDateTime(item.last_used_at), item.last_used_ip]
      .filter(Boolean)
      .join(' · ');
    return <span title={details}>{label}</span>;
  };

  const renderExpiry = (item: PersonalAccessToken) => {
    const status = expiryStatus(item.expires_at);
    if (status === 'never' || !item.expires_at) {
      return t('settings.accessTokens.never');
    }
    const date = formatDateOnly(item.expires_at);
    if (status === 'ok') return date;
    const expired = status === 'expired';
    return (
      <Badge variant={expired ? 'destructive' : 'warning'} title={date}>
        <TriangleAlert className="size-3 shrink-0" aria-hidden="true" />
        {expired
          ? t('settings.accessTokens.expired', { date, ...NO_ESCAPE })
          : t('settings.accessTokens.expiresSoon', { date, ...NO_ESCAPE })}
      </Badge>
    );
  };

  const renderRegenerateButton = (item: PersonalAccessToken) =>
    policy?.enabled ? (
      <Button
        type="button"
        variant="outline"
        size="sm"
        shape="pill"
        onClick={() => setTokenToRegenerate(item)}
        aria-label={t('settings.accessTokens.regenerate.aria', {
          name: item.name,
          ...NO_ESCAPE,
        })}
      >
        {t('settings.accessTokens.regenerate.action')}
      </Button>
    ) : null;

  const renderRevokeButton = (item: PersonalAccessToken) => (
    <Button
      type="button"
      variant="destructive-outline"
      size="sm"
      shape="pill"
      onClick={() => requestRevoke(item)}
      aria-label={t('settings.accessTokens.revokeAria', {
        name: item.name,
        ...NO_ESCAPE,
      })}
    >
      {t('settings.accessTokens.revoke')}
    </Button>
  );

  const renderPrefix = (item: PersonalAccessToken) => (
    <code className="text-muted-foreground font-mono text-xs whitespace-nowrap">
      {item.token_prefix}…
    </code>
  );

  const renderEmptyState = () => (
    <div className="flex w-full flex-col items-center justify-center py-12">
      <img
        src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
        alt=""
        className="mx-auto mb-6 h-32 w-32"
      />
      <p className="text-muted-foreground text-center text-lg">
        {t('settings.accessTokens.empty')}
      </p>
      {policy?.enabled && (
        <p className="text-muted-foreground mt-2 max-w-md text-center text-sm">
          {t('settings.accessTokens.emptyHint')}
        </p>
      )}
    </div>
  );

  const mobileField = (label: string, value: React.ReactNode) => (
    <div className="flex items-start justify-between gap-4 text-sm">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="text-foreground min-w-0 text-right">{value}</span>
    </div>
  );

  return (
    <div className="mt-8">
      <div className="relative flex flex-col">
        <div className="my-3 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-muted-foreground max-w-2xl text-sm leading-6">
            {t('settings.accessTokens.subtitle')}
          </p>
          {policy?.enabled && (
            <Button
              type="button"
              shape="pill"
              className="h-11 min-w-[108px] shrink-0 whitespace-normal"
              onClick={() => setCreateOpen(true)}
              disabled={limitReached}
              title={
                limitReached
                  ? t('settings.accessTokens.limitReached', {
                      count: policy.max_per_user,
                    })
                  : undefined
              }
            >
              {t('settings.accessTokens.createToken')}
            </Button>
          )}
        </div>

        {policy && !policy.enabled && (
          <Alert className="mt-2">
            <AlertDescription>
              {t('settings.accessTokens.disabledNotice')}
            </AlertDescription>
          </Alert>
        )}
        {policy?.enabled && limitReached && (
          <p className="text-muted-foreground mt-1 text-xs">
            {t('settings.accessTokens.limitReached', {
              count: policy.max_per_user,
            })}
          </p>
        )}
        {error && (
          <Alert variant="destructive" className="mt-2">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="border-border mt-5 mb-8 border-b" />

        {loading ? (
          <SkeletonLoader component="default" />
        ) : tokens.length === 0 ? (
          !error && renderEmptyState()
        ) : (
          <>
            {/* Desktop: table */}
            <TableContainer className="hidden lg:block">
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeader>{t('settings.accessTokens.name')}</TableHeader>
                    <TableHeader>
                      {t('settings.accessTokens.scopes')}
                    </TableHeader>
                    <TableHeader>
                      {t('settings.accessTokens.resources')}
                    </TableHeader>
                    <TableHeader>
                      {t('settings.accessTokens.createdAt')}
                    </TableHeader>
                    <TableHeader>
                      {t('settings.accessTokens.lastUsed')}
                    </TableHeader>
                    <TableHeader>
                      {t('settings.accessTokens.expires')}
                    </TableHeader>
                    <TableHeader align="right">
                      <span className="sr-only">
                        {t('settings.accessTokens.actions')}
                      </span>
                    </TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {tokens.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="max-w-[220px]">
                        <p
                          className="text-foreground truncate font-medium"
                          title={item.name}
                        >
                          {item.name}
                        </p>
                        {renderPrefix(item)}
                      </TableCell>
                      <TableCell className="max-w-[280px]">
                        <ScopeChips scopes={item.scopes} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {renderRestrictions(item)}
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        {item.created_at
                          ? formatDateOnly(item.created_at)
                          : '-'}
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        {renderLastUsed(item)}
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        {renderExpiry(item)}
                      </TableCell>
                      <TableCell align="right">
                        <div className="flex items-center justify-end gap-2">
                          {renderRegenerateButton(item)}
                          {renderRevokeButton(item)}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            {/* Mobile / tablet: cards */}
            <ul className="flex flex-col gap-4 lg:hidden">
              {tokens.map((item) => (
                <li
                  key={item.id}
                  className="bg-muted/60 flex flex-col gap-3 rounded-2xl p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p
                        className="text-foreground truncate text-sm font-semibold"
                        title={item.name}
                      >
                        {item.name}
                      </p>
                      {renderPrefix(item)}
                    </div>
                  </div>
                  <ScopeChips scopes={item.scopes} />
                  <div className="flex flex-col gap-1.5">
                    {mobileField(
                      t('settings.accessTokens.resources'),
                      renderRestrictions(item),
                    )}
                    {mobileField(
                      t('settings.accessTokens.createdAt'),
                      item.created_at ? formatDateOnly(item.created_at) : '-',
                    )}
                    {mobileField(
                      t('settings.accessTokens.lastUsed'),
                      renderLastUsed(item),
                    )}
                    {mobileField(
                      t('settings.accessTokens.expires'),
                      renderExpiry(item),
                    )}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {renderRegenerateButton(item)}
                    {renderRevokeButton(item)}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {policy && (
        <CreateAccessTokenModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          scopes={scopes}
          policy={policy}
          onCreated={handleCreated}
        />
      )}
      <AccessTokenCreatedModal
        token={created?.token ?? null}
        name={created?.personal_access_token.name ?? ''}
        regenerated={createdByRegenerate}
        onClose={() => setCreated(null)}
      />
      {policy && (
        <RegenerateAccessTokenModal
          item={tokenToRegenerate}
          policy={policy}
          onClose={() => setTokenToRegenerate(null)}
          onRegenerated={handleRegenerated}
        />
      )}
      <ConfirmationModal
        message={t('settings.accessTokens.revokeWarning', {
          name: tokenToRevoke?.name ?? '',
          ...NO_ESCAPE,
        })}
        modalState={revokeState}
        setModalState={setRevokeState}
        handleSubmit={confirmRevoke}
        submitLabel={t('settings.accessTokens.revoke')}
        variant="danger"
      />
    </div>
  );
}
