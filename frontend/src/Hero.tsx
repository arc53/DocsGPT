import { useDarkTheme, useMediaQuery } from './hooks';
import DocsGPT3 from './assets/cute_docsgpt3.svg';
import SourceDropdown from './components/SourceDropdown';
import { useSelector } from 'react-redux';
import { selectSourceDocs,selectSelectedDocs,selectConversations,selectModalStateDeleteConv } from './preferences/preferenceSlice';
export default function Hero({ className = '' }: { className?: string }) {
  // const isMobile = window.innerWidth <= 768;
  const { isMobile } = useMediaQuery();
  const [isDarkTheme] = useDarkTheme();
  const docs = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);
  const conversations = useSelector(selectConversations);
  const modalStateDeleteConv = useSelector(selectModalStateDeleteConv);
  return (
    <div
      className={`mt-14 mb-4 flex flex-col justify-end text-black-1000 dark:text-bright-gray lg:mt-6`}
    >
      <div className='h-full flex flex-col items-center justify-center'>
        <div>
          <span className='font-semibold text-4xl p-0'>DocsGPT</span>
          <img className='inline p-0 w-14 ml-2 mb-4' src={DocsGPT3} alt='docsgpt'/>
        </div>
       {/*  <SourceDropdown
                options={docs}
                selectedDocs={selectedDocs}
                setSelectedDocs={setSelectedDocs}
                isDocsListOpen={isDocsListOpen}
                setIsDocsListOpen={setIsDocsListOpen}
                handleDeleteClick={handleDeleteClick}
              /> */}
      </div>
      <div className='grid grid-cols-1 lg:grid-cols-2 items-center gap-3 sm:gap-6 text-xs md:text-sm'>
        <div className='border-2 w-full sm:w-112 px-6 py-4 rounded-full border-silver'>
          <p className='mb-1 font-semibold text-black dark:text-silver'>Chat with your documentation</p>
          <span className='text-gray-400'>Upload documents and get your answers</span>
        </div>
        <div className='border-2 w-full sm:w-112 px-6 py-4 rounded-full border-silver'>
          <p className='mb-1 font-semibold text-black dark:text-silver'>Chat with your documentation</p>
          <span className='text-gray-400'>Upload documents and get your answers</span>
        </div>
        <div className='border-2 w-full sm:w-112 px-6 py-4 rounded-full border-silver'>
          <p className='mb-1 font-semibold text-black dark:text-silver'>Chat with your documentation</p>
          <span className='text-gray-400'>Upload documents and get your answers</span>
        </div>
        <div className='border-2 w-full sm:w-112 px-6 py-4 rounded-full border-silver'>
          <p className='mb-1 font-semibold text-black dark:text-silver'>Chat with your documentation</p>
          <span className='text-gray-400'>Upload documents and get your answers</span>
        </div>
      </div>
    </div>
  );
}
