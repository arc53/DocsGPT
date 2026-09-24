import { CircleAlert, TriangleAlert } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import patService, {
  AccessTokenPolicy,
  AccessTokenScope,
  CreateAccessTokenResponse,
} from '../api/services/patService';
import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Modal } from '../components/ui/modal';
import { MultiSelect } from '../components/ui/multi-select';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Switch } from '../components/ui/switch';
import { selectToken } from '../preferences/preferenceSlice';
import {
  buildResourceFilter,
  defaultExpiry,
  eligibleFilterFamilies,
  expiryOptions,
  groupScopesByFamily,
  isScopeImplied,
  NO_ESCAPE,
  NO_EXPIRY,
  PICKER_FAMILIES,
  ResourceOption,
  scopesToSubmit,
  toResourceOptions,
} from '../settings/accessTokenUtils';
import { formatDateOnly } from '../utils/dateTimeUtils';

const MAX_NAME_LENGTH = 100;
const DAY_MS = 24 * 60 * 60 * 1000;

type ResourceState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; options: ResourceOption[] };

const RESOURCE_FETCHERS: Record<
  string,
  (token: string | null) => Promise<Response>
> = {
  agents: (token) => userService.getAgents(token),
  sources: (token) => userService.getDocs(token),
  prompts: (token) => userService.getPrompts(token),
  tools: (token) => userService.getUserTools(token),
};

interface CreateAccessTokenModalProps {
  open: boolean;
  onClose: () => void;
  scopes: AccessTokenScope[];
  policy: AccessTokenPolicy;
  onCreated: (created: CreateAccessTokenResponse) => void;
}

export default function CreateAccessTokenModal({
  open,
  onClose,
  scopes,
  policy,
  onCreated,
}: CreateAccessTokenModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [name, setName] = React.useState('');
  const [selectedScopes, setSelectedScopes] = React.useState<string[]>([]);
  const [expiry, setExpiry] = React.useState<number>(() =>
    defaultExpiry(policy),
  );
  const [restrict, setRestrict] = React.useState(false);
  const [resourceSelection, setResourceSelection] = React.useState<
    Record<string, string[]>
  >({});
  const [resources, setResources] = React.useState<
    Record<string, ResourceState>
  >({});
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Start from a clean form on every open; resource lists are refetched so a
  // freshly created agent/source shows up without a page reload.
  React.useEffect(() => {
    if (!open) return;
    setName('');
    setSelectedScopes([]);
    setExpiry(defaultExpiry(policy));
    setRestrict(false);
    setResourceSelection({});
    setResources({});
    setSubmitting(false);
    setError(null);
  }, [open, policy]);

  const scopeGroups = React.useMemo(
    () => groupScopesByFamily(scopes),
    [scopes],
  );
  const expiryChoices = React.useMemo(() => expiryOptions(policy), [policy]);
  const pickerFamilies = React.useMemo(
    () =>
      eligibleFilterFamilies(selectedScopes, policy.filterable_families).filter(
        (family) => PICKER_FAMILIES.includes(family),
      ),
    [selectedScopes, policy.filterable_families],
  );

  const loadResources = React.useCallback(
    (family: string) => {
      const fetcher = RESOURCE_FETCHERS[family];
      if (!fetcher) return;
      setResources((prev) => ({ ...prev, [family]: { status: 'loading' } }));
      fetcher(token)
        .then(async (response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const options = toResourceOptions(family, await response.json());
          setResources((prev) => ({
            ...prev,
            [family]: { status: 'ready', options },
          }));
        })
        .catch((err) => {
          console.error(`Failed to load ${family}:`, err);
          setResources((prev) => ({ ...prev, [family]: { status: 'error' } }));
        });
    },
    [token],
  );

  // Lazy: a family's list is only fetched once its picker is actually shown.
  React.useEffect(() => {
    if (!open || !restrict) return;
    pickerFamilies.forEach((family) => {
      if (!resources[family]) loadResources(family);
    });
  }, [open, restrict, pickerFamilies, resources, loadResources]);

  const toggleScope = (scope: string) => {
    setError(null);
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  };

  const familyLabel = (family: string) =>
    t(`settings.accessTokens.families.${family}`, { defaultValue: family });

  const trimmedName = name.trim();
  const canSubmit =
    trimmedName.length > 0 && selectedScopes.length > 0 && !submitting;

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await patService.create(
        {
          name: trimmedName,
          scopes: scopesToSubmit(selectedScopes, scopes),
          resource_filter: restrict
            ? buildResourceFilter(resourceSelection, pickerFamilies)
            : undefined,
          expires_in_days: expiry,
        },
        token,
      );
      onCreated(created);
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      setError(message || t('settings.accessTokens.create.error'));
    } finally {
      setSubmitting(false);
    }
  };

  const expiryLabel = (days: number) =>
    days === NO_EXPIRY
      ? t('settings.accessTokens.create.noExpiration')
      : t('settings.accessTokens.create.expiryDays', { count: days });

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && handleClose()}
      hideTitle
      title={t('settings.accessTokens.create.title')}
      size="lg"
      mobileVariant="sheet"
      isPerformingTask={submitting}
      contentClassName="max-h-[65vh]"
      footer={
        <>
          <Button
            type="button"
            variant="ghost"
            onClick={handleClose}
            disabled={submitting}
            size="lg"
            shape="pill"
          >
            {t('settings.accessTokens.create.cancel')}
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            size="lg"
            shape="pill"
          >
            {submitting ? (
              <span className="flex items-center gap-2">
                <Spinner size="small" />
                {t('settings.accessTokens.create.submitting')}
              </span>
            ) : (
              t('settings.accessTokens.create.submit')
            )}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-6 px-1"
        onSubmit={(e) => {
          e.preventDefault();
          handleSubmit();
        }}
      >
        <div>
          <h2 className="text-foreground dark:text-foreground text-xl font-semibold">
            {t('settings.accessTokens.create.title')}
          </h2>
          <p className="text-muted-foreground mt-2 text-sm">
            {t('settings.accessTokens.create.subtitle')}
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pat-name">
              {t('settings.accessTokens.create.name')}
              <span className="text-destructive">*</span>
            </Label>
            <Input
              id="pat-name"
              type="text"
              value={name}
              maxLength={MAX_NAME_LENGTH}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
              placeholder={t('settings.accessTokens.create.namePlaceholder')}
              autoComplete="off"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pat-expiry">
              {t('settings.accessTokens.create.expiration')}
            </Label>
            <Select
              value={String(expiry)}
              onValueChange={(value) => setExpiry(Number(value))}
            >
              <SelectTrigger id="pat-expiry" className="w-full" size="lg">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {expiryChoices.map((days) => (
                  <SelectItem key={days} value={String(days)}>
                    {expiryLabel(days)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {expiry === NO_EXPIRY ? (
              <Alert variant="warning">
                <TriangleAlert className="size-4" aria-hidden="true" />
                <AlertDescription>
                  {t('settings.accessTokens.create.noExpirationHint')}
                </AlertDescription>
              </Alert>
            ) : (
              <p className="text-muted-foreground text-xs">
                {t('settings.accessTokens.create.expiresOn', {
                  date: formatDateOnly(
                    new Date(Date.now() + expiry * DAY_MS).toISOString(),
                  ),
                  ...NO_ESCAPE,
                })}
              </p>
            )}
          </div>
        </div>

        <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
          <legend className="text-foreground dark:text-foreground text-sm font-semibold">
            {t('settings.accessTokens.create.scopes')}
            <span className="text-destructive">*</span>
          </legend>
          <p className="text-muted-foreground text-xs">
            {t('settings.accessTokens.create.scopesHint')}
          </p>
          <div className="border-border dark:border-border divide-border flex flex-col divide-y rounded-xl border">
            {scopeGroups.map((group) => (
              <div
                key={group.family}
                className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:gap-4"
              >
                <p className="text-foreground dark:text-foreground w-32 shrink-0 text-sm font-medium capitalize">
                  {familyLabel(group.family)}
                </p>
                <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                  {group.scopes.map((scope) => {
                    const implied = isScopeImplied(scope.name, selectedScopes);
                    const checked =
                      implied || selectedScopes.includes(scope.name);
                    const id = `pat-scope-${scope.name}`;
                    return (
                      <label
                        key={scope.name}
                        htmlFor={id}
                        title={
                          implied
                            ? t('settings.accessTokens.create.impliedByWrite')
                            : undefined
                        }
                        className={`flex items-start gap-3 ${
                          implied
                            ? 'cursor-not-allowed opacity-70'
                            : 'cursor-pointer'
                        }`}
                      >
                        <input
                          id={id}
                          type="checkbox"
                          checked={checked}
                          disabled={implied}
                          onChange={() => toggleScope(scope.name)}
                          className="accent-primary border-input mt-0.5 size-4 shrink-0 rounded-sm bg-transparent dark:[color-scheme:dark]"
                        />
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <code className="text-foreground dark:text-foreground font-mono text-xs font-medium">
                            {scope.name}
                          </code>
                          <span className="text-muted-foreground text-xs leading-relaxed">
                            {scope.description}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </fieldset>

        {policy.filterable_families.length > 0 && (
          <div className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-4">
              <div className="flex flex-col gap-1">
                <Label htmlFor="pat-restrict" className="text-sm font-semibold">
                  {t('settings.accessTokens.create.restrict')}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t('settings.accessTokens.create.restrictHint')}
                </p>
              </div>
              <Switch
                id="pat-restrict"
                checked={restrict}
                onCheckedChange={setRestrict}
              />
            </div>
            {restrict && pickerFamilies.length === 0 && (
              <p className="text-muted-foreground bg-muted rounded-lg px-4 py-2 text-xs">
                {t('settings.accessTokens.create.restrictNoFamilies')}
              </p>
            )}
            {restrict &&
              pickerFamilies.map((family) => {
                const state = resources[family];
                return (
                  <div key={family} className="flex flex-col gap-1.5">
                    <Label className="capitalize">{familyLabel(family)}</Label>
                    {!state || state.status === 'loading' ? (
                      <div className="flex h-10 items-center">
                        <Spinner size="small" />
                      </div>
                    ) : state.status === 'error' ? (
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="text-destructive">
                          {t('settings.accessTokens.create.resourcesError')}
                        </span>
                        <Button
                          type="button"
                          variant="link"
                          size="xs"
                          onClick={() => loadResources(family)}
                        >
                          {t('settings.accessTokens.create.retry')}
                        </Button>
                      </div>
                    ) : (
                      <MultiSelect
                        options={state.options}
                        selected={resourceSelection[family] ?? []}
                        onChange={(ids) =>
                          setResourceSelection((prev) => ({
                            ...prev,
                            [family]: ids,
                          }))
                        }
                        placeholder={t(
                          'settings.accessTokens.create.allSelected',
                        )}
                        emptyText={t(
                          'settings.accessTokens.create.noResources',
                        )}
                        searchPlaceholder={t(
                          'settings.accessTokens.create.searchResources',
                        )}
                        modal
                      />
                    )}
                  </div>
                );
              })}
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </form>
    </Modal>
  );
}
