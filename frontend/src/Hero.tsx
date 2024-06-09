import { Fragment } from 'react';
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
    <div
      className={`mt-14 mb-4 flex w-full flex-col justify-end text-black-1000 dark:text-bright-gray sm:w-full lg:mt-6`}
    >
      <div className="flex h-full w-full flex-col items-center justify-center">
        <div className="flex items-center">
          <span className="p-0 text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14 p-0" src={DocsGPT3} alt="docsgpt" />
        </div>

        <div className="mb-4 flex flex-col items-center justify-center dark:text-white"></div>
      </div>
      <div className="grid w-full grid-cols-1 items-center gap-4 self-center text-xs sm:w-auto sm:gap-6 md:text-sm  lg:grid-cols-2">
        {demos?.map(
          (demo: { header: string; query: string }, key: number) =>
            demo.header &&
            demo.query && (
              <Fragment key={key}>
                <button
                  onClick={() => handleQuestion({ question: demo.query })}
                  className="w-full rounded-full border-2 border-silver px-6 py-4 text-left hover:border-gray-4000 dark:hover:border-gray-3000 xl:min-w-[24vw]"
                >
                  <p className="mb-1 font-semibold text-black dark:text-silver">
                    {demo.header}
                  </p>
                  <span className="text-gray-400">{demo.query}</span>
                </button>
              </Fragment>
            ),
        )}
      </div>
    </div>
  );
}
