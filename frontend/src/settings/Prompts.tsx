import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import FilterSelect from '../components/FilterSelect';
import PageToolbar from '../components/PageToolbar';
import RoleBadge from '../components/RoleBadge';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { RadioGroup, RadioGroupItem } from '../components/ui/radio-group';
import { SectionHeader } from '../components/ui/section-header';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { shownFilters, useUrlFilter } from '../hooks/useUrlFilter';
import type { Prompt } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import {
  chooseChatPrompt,
  DEFAULT_CHAT_PROMPT,
} from '../preferences/chatPrompt';
import {
  selectPrompt,
  selectToken,
  setPrompt,
  setPrompts,
} from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { agentUseCount } from '../utils/resourceUsage';
import UsedByAgents from './UsedByAgents';
import usePromptActions from './usePromptActions';

const USAGE_FILTERS = ['all', 'inUse', 'unused'] as const;
type UsageFilter = (typeof USAGE_FILTERS)[number];

/** The page's sections, by the prompt's `type`. */
const SECTIONS = [
  { key: 'included', type: 'public' },
  { key: 'yours', type: 'private' },
  { key: 'shared', type: 'team' },
] as const;

/** The kind track's values: All, then one per section. */
const KINDS = ['all', ...SECTIONS.map((section) => section.key)] as const;
type KindFilter = (typeof KINDS)[number];

const PRESETS = ['default', 'creative', 'strict'];

/**
 * Settings › Prompts: the presets, the user's own prompts and the ones shared
 * with them, as cards. A radio on each card picks the prompt chats without an
 * agent use (kept on the server); the ⋯ opens, duplicates, shares or deletes.
 */
export default function Prompts() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const chatPrompt = useSelector(selectPrompt);

  const [prompts, setPromptList] = React.useState<Prompt[]>([]);
  const [loading, setLoading] = React.useState(true);
  // The first load failed: an error with Retry, not an empty page.
  const [loadFailed, setLoadFailed] = React.useState(false);
  const [searchTerm, setSearchTerm] = React.useState('');
  // The address holds the kind and usage filters, so Back and a reload
  // keep them.
  const [kind, setKind] = useUrlFilter(KINDS, { name: 'kind' });
  const [usage, setUsage] = useUrlFilter(USAGE_FILTERS, { name: 'usage' });

  const showList = (list: Prompt[]) => {
    setPromptList(list);
    // The pickers (agent form, Teams) read the same list.
    dispatch(setPrompts(list));
  };

  // `quiet`: a reload after a change keeps the cards on screen.
  const loadPrompts = (quiet = false) => {
    if (!quiet) setLoading(true);
    return userService
      .getPrompts(token)
      .then((response: Response) => {
        if (!response.ok)
          throw new Error(`Failed to load prompts (${response.status})`);
        return response.json();
      })
      .then((data: Prompt[]) => {
        showList(Array.isArray(data) ? data : []);
        setLoadFailed(false);
      })
      .catch((error: unknown) => {
        console.error('Error fetching prompts:', error);
        if (!quiet) setLoadFailed(true);
      })
      .finally(() => setLoading(false));
  };

  React.useEffect(() => {
    loadPrompts();
  }, [token]);

  const { openPrompt, addPrompt, menuOptions, modals } = usePromptActions({
    prompts,
    onSaved: () => loadPrompts(true),
    onDeleted: (deleted) => {
      showList(prompts.filter((prompt) => prompt.id !== deleted.id));
      // The server reads a deleted chat prompt back as default.
      if (deleted.id === chatPrompt.id)
        dispatch(setPrompt(DEFAULT_CHAT_PROMPT));
    },
  });

  const pickChatPrompt = (id: string) => {
    const prompt = prompts.find((item) => item.id === id);
    if (!prompt) return;
    dispatch(chooseChatPrompt(prompt, token)).then((saved) => {
      if (!saved)
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: t('settings.prompts.chatPromptFailed'),
          }),
        );
    });
  };

  /** In use: an agent uses it, or chats without an agent do. */
  const isInUse = (prompt: Prompt) =>
    agentUseCount(prompt.used_by) > 0 || prompt.id === chatPrompt.id;
  const matchesUsage = (prompt: Prompt, key: UsageFilter) =>
    key === 'all' || (key === 'inUse') === isInUse(prompt);
  const matchesKind = (prompt: Prompt, key: KindFilter) =>
    key === 'all' ||
    SECTIONS.some((s) => s.key === key && s.type === prompt.type);
  // Each filter counts with the other one applied.
  const kindCounts = Object.fromEntries(
    KINDS.map((key) => [
      key,
      prompts.filter((p) => matchesUsage(p, usage) && matchesKind(p, key))
        .length,
    ]),
  ) as Record<KindFilter, number>;
  const usageCounts = Object.fromEntries(
    USAGE_FILTERS.map((key) => [
      key,
      prompts.filter((p) => matchesKind(p, kind) && matchesUsage(p, key))
        .length,
    ]),
  ) as Record<UsageFilter, number>;
  // No pill leads to an empty list; with only All left there is no track.
  const kinds = shownFilters(KINDS, kind, kindCounts);

  const query = searchTerm.trim().toLowerCase();
  const shown = prompts.filter(
    (prompt) =>
      matchesKind(prompt, kind) &&
      matchesUsage(prompt, usage) &&
      prompt.name.toLowerCase().includes(query),
  );
  const sections = SECTIONS.map((section) => ({
    ...section,
    prompts: shown.filter((prompt) => prompt.type === section.type),
  })).filter((section) => section.prompts.length > 0);

  const renderCard = (prompt: Prompt) => {
    const inChats = prompt.id === chatPrompt.id;
    // The presets open with the same lines, so they say what they do.
    const description = PRESETS.includes(prompt.id)
      ? t(`settings.prompts.presets.${prompt.id}`)
      : prompt.preview;
    const options = menuOptions(prompt);
    return (
      // DESIGN "A clickable card that holds a link": a stretched button
      // opens the prompt; the menu, the usage link and the radio sit above
      // it, never inside.
      <Card
        key={prompt.id}
        variant="filled"
        padding="lg"
        interactive="within"
        className="h-full"
      >
        <button
          type="button"
          onClick={() => openPrompt(prompt)}
          className="flex w-full min-w-0 cursor-pointer pr-9 text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
        >
          <CardTitle className="min-w-0 truncate" title={prompt.name}>
            {prompt.name}
          </CardTitle>
        </button>
        {options.length > 0 ? (
          <div className="absolute top-5 right-4 z-10">
            <ActionMenu
              options={options}
              triggerLabel={t('settings.prompts.actions', {
                interpolation: { escapeValue: false },
                name: prompt.name,
              })}
            />
          </div>
        ) : null}
        {description ? (
          <CardDescription size="xs" className="line-clamp-3 wrap-break-word">
            {description}
          </CardDescription>
        ) : null}
        <div className="flex flex-wrap gap-1 empty:hidden">
          {inChats ? <Badge>{t('settings.usage.inChats')}</Badge> : null}
          <RoleBadge item={prompt} />
        </div>
        <CardFooter className="mt-auto w-full">
          {agentUseCount(prompt.used_by) > 0 ? (
            <span className="relative z-10 min-w-0">
              <UsedByAgents usage={prompt.used_by} />
            </span>
          ) : null}
          <span className="relative z-10 ml-auto flex shrink-0">
            <RadioGroupItem
              value={prompt.id}
              aria-label={t('settings.prompts.useInChats', {
                interpolation: { escapeValue: false },
                name: prompt.name,
              })}
            />
          </span>
        </CardFooter>
      </Card>
    );
  };

  return (
    <div>
      <PageToolbar
        intro={t('settings.prompts.subtitle')}
        search={
          <SearchInput
            maxLength={256}
            label={t('settings.prompts.searchPlaceholder')}
            name="prompt-search-input"
            id="prompt-search-input"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        }
        action={
          <Button type="button" size="field" shape="pill" onClick={addPrompt}>
            {t('settings.prompts.addPrompt')}
          </Button>
        }
        divider
      >
        {!loading && !loadFailed && prompts.length > 0 ? (
          <div className="mb-6 flex flex-wrap items-center gap-3 empty:hidden">
            {kinds.length > 0 ? (
              <ToggleGroup
                type="single"
                value={kind}
                onValueChange={(value) => value && setKind(value as KindFilter)}
                aria-label={t('settings.prompts.kindFilterLabel')}
              >
                {kinds.map((key) => (
                  <ToggleGroupItem
                    key={key}
                    value={key}
                    count={kindCounts[key]}
                  >
                    {key === 'all'
                      ? t('settings.prompts.filters.all')
                      : key === 'shared'
                        ? t('settings.prompts.kinds.shared')
                        : t(`settings.prompts.sections.${key}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            ) : null}
            <FilterSelect
              value={usage}
              onValueChange={setUsage}
              values={USAGE_FILTERS}
              counts={usageCounts}
              labelOf={(value) => t(`settings.usage.filters.${value}`)}
              ariaLabel={t('settings.usage.filterLabel')}
            />
          </div>
        ) : null}
      </PageToolbar>
      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <SkeletonLoader component="toolCards" count={6} />
        </div>
      ) : loadFailed ? (
        <EmptyState
          tone="destructive"
          illustration="none"
          title={t('settings.prompts.loadError')}
          onRetry={() => loadPrompts()}
        />
      ) : sections.length === 0 ? (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.prompts.noPromptsFound')}
        />
      ) : (
        // One group across the sections: one Tab stop, arrow keys between
        // the cards, and one prompt picked.
        <RadioGroup
          value={chatPrompt.id}
          onValueChange={pickChatPrompt}
          aria-label={t('settings.prompts.chatPromptLabel')}
        >
          <div className="flex flex-col gap-8">
            {sections.map((section) => (
              <section key={section.key} className="flex flex-col gap-3">
                <SectionHeader
                  as="h2"
                  size="sm"
                  title={t(`settings.prompts.sections.${section.key}`)}
                  count={section.prompts.length}
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {section.prompts.map(renderCard)}
                </div>
              </section>
            ))}
          </div>
        </RadioGroup>
      )}
      {modals}
    </div>
  );
}
