import { useDarkTheme, useMediaQuery } from './hooks';
import DocsGPT3 from './assets/cute_docsgpt3.svg';
import { useSelector } from 'react-redux';
import { selectConversations } from './preferences/preferenceSlice';
import Arrow2 from './assets/dropdown-arrow.svg';
export default function Hero({ className = '' }: { className?: string }) {
  // const isMobile = window.innerWidth <= 768;
  const { isMobile } = useMediaQuery();
  const [isDarkTheme] = useDarkTheme();
  const conversations = useSelector(selectConversations);
  return (
    <div
      className={`mt-14 mb-4 flex w-11/12 sm:w-7/12 flex-col justify-end text-black-1000 dark:text-bright-gray lg:mt-6`}
    >
      <div className="flex h-full w-full flex-col items-center justify-center">
        <div className="flex items-center">
          <span className="p-0 text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14 p-0" src={DocsGPT3} alt="docsgpt" />
        </div>

        <div className="mb-4 flex flex-col items-center justify-center dark:text-white">
          
        </div>
      </div>
      <div className="grid w-full grid-cols-1 items-center gap-4 self-center text-xs sm:gap-6 md:text-sm  lg:grid-cols-2">
        <div className="w-full rounded-full border-2 border-silver px-6 py-4">
          <p className="mb-1 font-semibold text-black dark:text-silver">
            Chat with your documentation
          </p>
          <span className="text-gray-400">
            Upload documents and get your answers
          </span>
        </div>
        <div className="w-full rounded-full border-2 border-silver px-6 py-4">
          <p className="mb-1 font-semibold text-black dark:text-silver">
            Chat with your documentation
          </p>
          <span className="text-gray-400">
            Upload documents and get your answers
          </span>
        </div>
        <div className="w-full rounded-full border-2 border-silver px-6 py-4">
          <p className="mb-1 font-semibold text-black dark:text-silver">
            Chat with your documentation
          </p>
          <span className="text-gray-400">
            Upload documents and get your answers
          </span>
        </div>
        <div className="w-full rounded-full border-2 border-silver px-6 py-4">
          <p className="mb-1 font-semibold text-black dark:text-silver">
            Chat with your documentation
          </p>
          <span className="text-gray-400">
            Upload documents and get your answers
          </span>
        </div>
      </div>
    </div>  );
}
