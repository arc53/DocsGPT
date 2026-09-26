import { ChevronDown } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ResearchIcon from '../assets/research.svg';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { Spinner } from '../components/ui/spinner';
import { ResearchState } from './conversationModels';
import { cn } from '@/lib/utils';

const SmallCheck = () => (
  <svg
    className="text-success size-3"
    fill="none"
    viewBox="0 0 24 24"
    stroke="currentColor"
    strokeWidth={3}
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
);

const SmallPending = () => (
  <div className="border-muted-foreground size-2.5 rounded-full border" />
);

function StatusText({ status, elapsed }: { status: string; elapsed?: number }) {
  const { t } = useTranslation();
  const labels: Record<string, string> = {
    planning: t('conversation.research.planning'),
    researching: t('conversation.research.researching'),
    synthesizing: t('conversation.research.synthesizing'),
    complete: t('conversation.research.complete'),
  };
  const elapsed_str = elapsed ? ` \u00B7 ${Math.round(elapsed)}s` : '';
  return (
    <span className="text-muted-foreground text-xs">
      {status === 'complete' ? (
        <>
          <span className="text-success">{labels.complete}</span>
          {elapsed_str}
        </>
      ) : (
        <>
          {labels[status] || status}
          {elapsed_str}
        </>
      )}
    </span>
  );
}

export default function ResearchProgress({
  research,
}: {
  research: ResearchState;
}) {
  const { t } = useTranslation();
  const { plan, status, elapsed_seconds } = research;
  const [isExpanded, setIsExpanded] = useState(true);

  // Auto-collapse when synthesis starts (report is streaming)
  useEffect(() => {
    if (status === 'synthesizing' || status === 'complete') {
      setIsExpanded(false);
    }
  }, [status]);

  if (!plan && !status) return null;

  const completedSteps =
    plan?.filter((s) => s.status === 'complete').length ?? 0;
  const totalSteps = plan?.length ?? 0;

  // Collapsed: single-line summary
  const summaryText =
    totalSteps > 0
      ? t('conversation.research.researched', { count: completedSteps })
      : t('conversation.research.title');

  return (
    <div className="mb-4 flex w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
      {/* Header row — matches Reasoning / Sources pattern */}
      <div className="my-2 flex flex-row items-center gap-3">
        <Avatar
          src={ResearchIcon}
          alt={t('conversation.research.title')}
          className="h-[26px] w-[30px]"
          imgClassName="h-full w-full object-fill"
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="-ml-2.5"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <p className="text-sm font-semibold">
            {isExpanded ? t('conversation.research.title') : summaryText}
          </p>
          <ChevronDown
            className={cn(
              'text-muted-foreground transition-transform duration-200',
              isExpanded && 'rotate-180',
            )}
          />
        </Button>
        {status && <StatusText status={status} elapsed={elapsed_seconds} />}
      </div>

      {/* Expanded: vertical timeline of steps */}
      {isExpanded && plan && plan.length > 0 && (
        <div className="animate-in fade-in mr-5 ml-[42px] max-w-[90vw] duration-160 ease-out motion-reduce:animate-none md:max-w-[70vw] lg:max-w-[50vw]">
          <div className="flex flex-col">
            {plan.map((step, i) => {
              const isLast = i === plan.length - 1;
              return (
                <div key={i} className="flex items-stretch gap-3">
                  {/* Timeline: dot + vertical line */}
                  <div className="flex flex-col items-center pt-1">
                    <div className="flex size-4 flex-shrink-0 items-center justify-center">
                      {step.status === 'complete' ? (
                        <SmallCheck />
                      ) : step.status === 'researching' ? (
                        <Spinner size="xs" className="text-primary" />
                      ) : (
                        <SmallPending />
                      )}
                    </div>
                    {!isLast && <div className="bg-border mt-1 w-px flex-1" />}
                  </div>
                  {/* Step content */}
                  <div className="pb-3">
                    <p
                      className={cn(
                        'text-sm',
                        step.status === 'complete'
                          ? 'text-foreground'
                          : step.status === 'researching'
                            ? 'text-primary font-medium'
                            : 'text-muted-foreground',
                      )}
                    >
                      {step.query}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
