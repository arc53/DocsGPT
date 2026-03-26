import { useEffect, useState } from 'react';
import ResearchIcon from '../assets/research.svg';
import Avatar from '../components/Avatar';
import { ResearchState } from './conversationModels';

const SmallCheck = () => (
  <svg className="h-3 w-3 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
);

const SmallSpinner = () => (
  <svg className="h-3 w-3 animate-spin text-purple-500" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
);

const SmallPending = () => (
  <div className="h-2.5 w-2.5 rounded-full border-[1.5px] border-gray-400 dark:border-gray-500" />
);

function StatusText({ status, elapsed }: { status: string; elapsed?: number }) {
  const labels: Record<string, string> = {
    planning: 'Planning research...',
    researching: 'Researching...',
    synthesizing: 'Writing report...',
    complete: 'Complete',
  };
  const elapsed_str = elapsed ? ` \u00B7 ${Math.round(elapsed)}s` : '';
  return (
    <span className="text-xs text-gray-500 dark:text-gray-400">
      {status === 'complete' ? (
        <>
          <span className="text-green-600 dark:text-green-400">{labels.complete}</span>
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
  const { plan, status, elapsed_seconds } = research;
  const [isExpanded, setIsExpanded] = useState(true);

  // Auto-collapse when synthesis starts (report is streaming)
  useEffect(() => {
    if (status === 'synthesizing' || status === 'complete') {
      setIsExpanded(false);
    }
  }, [status]);

  if (!plan && !status) return null;

  const completedSteps = plan?.filter((s) => s.status === 'complete').length ?? 0;
  const totalSteps = plan?.length ?? 0;

  // Collapsed: single-line summary
  const summaryText = totalSteps > 0
    ? `Researched ${completedSteps} topic${completedSteps !== 1 ? 's' : ''}`
    : 'Research';

  return (
    <div className="mb-4 flex w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
      {/* Header row — matches Reasoning / Sources pattern */}
      <div className="my-2 flex flex-row items-center gap-3">
        <Avatar
          className="h-[26px] w-[30px] text-xl"
          avatar={
            <img
              src={ResearchIcon}
              alt="Research"
              className="h-full w-full object-fill"
            />
          }
        />
        <button
          className="flex flex-row items-center gap-2"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <p className="text-sm font-semibold">
            {isExpanded ? 'Research' : summaryText}
          </p>
          <svg
            className={`h-4 w-4 text-gray-500 transition-transform duration-200 dark:text-gray-400 ${isExpanded ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {status && <StatusText status={status} elapsed={elapsed_seconds} />}
      </div>

      {/* Expanded: vertical timeline of steps */}
      {isExpanded && plan && plan.length > 0 && (
        <div className="fade-in mr-5 ml-[42px] max-w-[90vw] md:max-w-[70vw] lg:max-w-[50vw]">
          <div className="space-y-0">
            {plan.map((step, i) => {
              const isLast = i === plan.length - 1;
              return (
                <div key={i} className="flex items-stretch gap-3">
                  {/* Timeline: dot + vertical line */}
                  <div className="flex flex-col items-center pt-1">
                    <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center">
                      {step.status === 'complete' ? (
                        <SmallCheck />
                      ) : step.status === 'researching' ? (
                        <SmallSpinner />
                      ) : (
                        <SmallPending />
                      )}
                    </div>
                    {!isLast && (
                      <div className="mt-1 w-px flex-1 bg-gray-300 dark:bg-gray-600" />
                    )}
                  </div>
                  {/* Step content */}
                  <div className={`pb-3 ${isLast ? '' : ''}`}>
                    <p className={`text-sm ${
                      step.status === 'complete'
                        ? 'text-gray-700 dark:text-gray-300'
                        : step.status === 'researching'
                          ? 'font-medium text-purple-700 dark:text-purple-300'
                          : 'text-gray-500 dark:text-gray-500'
                    }`}>
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
