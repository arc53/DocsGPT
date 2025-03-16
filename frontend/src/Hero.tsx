import DocsGPT3 from './assets/cute_docsgpt3.svg';
import { useTranslation } from 'react-i18next';

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
    <div className="flex h-full w-full flex-col text-black-1000 dark:text-bright-gray items-center justify-between">
      {/* Header Section */}
      <div className="flex flex-col items-center justify-center flex-grow pt-8 md:pt-0">
        <div className="flex items-center mb-4">
          <span className="text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14" src={DocsGPT3} alt="docsgpt" />
        </div>
      </div>

      {/* Demo Buttons Section */}
      <div className="w-full max-w-full mb-8 md:mb-16">
        <div className="grid grid-cols-1 md:grid-cols-1 lg:grid-cols-2 gap-3 md:gap-4 text-xs">
          {demos?.map(
            (demo: { header: string; query: string }, key: number) =>
              demo.header &&
              demo.query && (
                <button
                  key={key}
                  onClick={() => handleQuestion({ question: demo.query })}
                  className="w-full rounded-[66px] border bg-transparent px-6 py-[14px] text-left transition-colors
                    border-dark-gray text-just-black hover:bg-cultured
                    dark:border-dim-gray dark:text-chinese-white dark:hover:bg-charleston-green"
                >
                  <p className="mb-2 font-semibold text-black-1000 dark:text-bright-gray">
                    {demo.header}
                  </p>
                  <span className="text-gray-700 dark:text-gray-300 opacity-60 line-clamp-2">
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
