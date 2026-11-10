import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { EmptyState } from '../components/ui/empty-state';
import { Skeleton } from '../components/ui/skeleton';
import DetailBreadcrumb from '../navigation/DetailBreadcrumb';
import { PromptEditor, type PromptEditorProps } from './PromptEditor';

export type PromptViewProps = PromptEditorProps & {
  /** The crumb back to where the prompt was opened from. */
  parent: { label: string; onClick: () => void };
  /** The crumb's last part: the prompt's name, or "Add prompt". */
  label: string;
  /** The crumb row's buttons (`field` pills: Improve, Save), before the ⋯. */
  actions?: ReactNode;
  /** The prompt's ⋯ (`ActionMenu size="toolbar"`), last in the crumb row. */
  menu?: ReactNode;
  /** One muted line under the crumb row (the agents that use it). */
  byline?: ReactNode;
  /** The text is still loading: a placeholder stands in for the fields. */
  loading?: boolean;
  /** The text didn't load: an error with Try again stands in for them. */
  onRetry?: () => void;
  /** An Alert about the open prompt (a refused save), above the fields. */
  notice?: ReactNode;
};

/**
 * A prompt as a detail page inside a list section (PATTERNS "A detail page
 * inside a list section"): the crumb row (DetailBreadcrumb, then the page's
 * buttons and the ⋯ last), an optional byline, and the PromptEditor on the
 * page's background. A host places it where its list was (Settings ›
 * Prompts) or inside its own form, and docks the drafter's drawer beside
 * it.
 */
export function PromptView({
  parent,
  label,
  actions,
  menu,
  byline,
  loading = false,
  onRetry,
  notice,
  ...editor
}: PromptViewProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-5" data-slot="prompt-view">
      <div className="flex min-h-9.5 items-center justify-between gap-3">
        <DetailBreadcrumb
          parentLabel={parent.label}
          currentLabel={label}
          onParentClick={parent.onClick}
        />
        {(actions || menu) && (
          <div className="flex shrink-0 items-center gap-2">
            {actions}
            {menu}
          </div>
        )}
      </div>
      {byline && <p className="text-muted-foreground text-sm">{byline}</p>}
      {onRetry ? (
        <EmptyState
          tone="destructive"
          illustration="none"
          title={t('settings.prompts.loadPromptError')}
          onRetry={onRetry}
        />
      ) : loading ? (
        <div className="flex flex-col gap-5" data-slot="prompt-view-loading">
          <Skeleton className="h-9.5 rounded-md" />
          <Skeleton className="h-48 rounded-2xl md:h-64 lg:h-80" />
        </div>
      ) : (
        <>
          {notice}
          <PromptEditor {...editor} />
        </>
      )}
    </div>
  );
}
