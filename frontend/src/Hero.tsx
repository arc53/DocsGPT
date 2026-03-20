import { useTranslation } from 'react-i18next';

import DocsGPT3 from './assets/cute_docsgpt3.svg';
import DropdownModel from './components/DropdownModel';

export default function Hero({
  handleQuestion,
}: {
  handleQuestion: ({
    question,
    isRetry,
  }: {
    question: string;
    isRetry?: boolean;
  }) => void;
}) {
  const { t } = useTranslation();
  const demos = t('demo', { returnObjects: true }) as Array<{
    header: string;
    query: string;
  }>;

  return (
    <div className="text-black-1000 dark:text-foreground flex h-full w-full flex-col items-center justify-between">
      {/* Header Section */}
      <div className="flex grow flex-col items-center justify-center pt-8 md:pt-0">
        <div className="mb-px flex items-center">
          <span className="text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14" src={DocsGPT3} alt="docsgpt" />
        </div>
        {/* Model Selector */}
        <div className="relative w-72">
          <DropdownModel />
        </div>
      </div>

      {/* Demo Buttons Section */}
      <div className="mb-3 w-full max-w-full md:mb-3">
        <div className="grid grid-cols-1 gap-3 text-xs md:grid-cols-1 md:gap-4 lg:grid-cols-2">
          {demos?.map(
            (demo: { header: string; query: string }, key: number) =>
              demo.header &&
              demo.query && (
                <button
                  key={key}
                  onClick={() => handleQuestion({ question: demo.query })}
                  className={`border-border text-foreground hover:bg-muted bg-card w-full rounded-[66px] border px-6 py-3.5 text-left transition-colors ${key >= 2 ? 'hidden md:block' : ''}`}
                >
                  <p className="text-black-1000 dark:text-foreground mb-2 font-semibold">
                    {demo.header}
                  </p>
                  <span className="line-clamp-2 text-gray-700 opacity-60 dark:text-gray-300">
                    {demo.query}
                  </span>
                </button>
              ),
          )}
        </div>
      </div>
    </div>
  );
}
