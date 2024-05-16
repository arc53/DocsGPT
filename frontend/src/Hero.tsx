import DocsGPT3 from './assets/cute_docsgpt3.svg';
const demos: { header: string; query: string }[] = [
  {
    header: 'Learn about DocsGPT',
    query: 'What is DocsGPT ?',
  },
  {
    header: 'Summarise documentation',
    query: 'Summarise current context',
  },
  {
    header: 'Write Code',
    query: 'Write code for api request for /api/answer',
  },
  {
    header: 'Learning Assistance',
    query: 'Write potential questions that can be answered by context',
  },
];

export default function Hero({
  handleQuestion,
}: {
  handleQuestion: (question: string) => void;
}) {
  return (
    <div
      className={`mt-14 mb-4 flex w-11/12 flex-col justify-end text-black-1000 dark:text-bright-gray sm:w-7/12 lg:mt-6`}
    >
      <div className="flex h-full w-full flex-col items-center justify-center">
        <div className="flex items-center">
          <span className="p-0 text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14 p-0" src={DocsGPT3} alt="docsgpt" />
        </div>

        <div className="mb-4 flex flex-col items-center justify-center dark:text-white"></div>
      </div>
      <div className="grid w-full grid-cols-1 items-center gap-4 self-center text-xs sm:gap-6 md:text-sm  lg:grid-cols-2">
        {demos.map((demo) => (
          <>
            <button
              onClick={() => handleQuestion(demo.query)}
              className="w-full rounded-full border-2 border-silver px-6 py-4 text-left hover:border-gray-4000 dark:hover:border-gray-3000"
            >
              <p className="mb-1 font-semibold text-black dark:text-silver">
                {demo.header}
              </p>
              <span className="text-gray-400">{demo.query}</span>
            </button>
          </>
        ))}
      </div>
    </div>
  );
}
