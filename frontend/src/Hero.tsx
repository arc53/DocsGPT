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
    <div className="flex h-full w-full flex-col items-center justify-between text-black-1000 dark:text-bright-gray">
      {/* Header Section */}
      <div className="flex flex-grow flex-col items-center justify-center pt-8 md:pt-0">
        <div className="mb-4 flex items-center">
          <span className="text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14" src={DocsGPT3} alt="docsgpt" />
        </div>
      </div>

      {/* Demo Buttons Section */}
      <div className="mb-8 w-full max-w-full md:mb-16">
        <div className="grid grid-cols-1 gap-3 text-xs md:grid-cols-1 md:gap-4 lg:grid-cols-2">
          {demos?.map(
            (demo: { header: string; query: string }, key: number) =>
              demo.header &&
              demo.query && (
                <button
                  key={key}
                  onClick={() => handleQuestion({ question: demo.query })}
                  className={`w-full rounded-[66px] border border-dark-gray bg-transparent px-6 py-[14px] text-left text-just-black transition-colors hover:bg-cultured dark:border-dim-gray dark:text-chinese-white dark:hover:bg-charleston-green ${key >= 2 ? 'hidden md:block' : ''} // Show only 2 buttons on mobile`}
                >
                  <p className="mb-2 font-semibold text-black-1000 dark:text-bright-gray">
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
