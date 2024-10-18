import { useState, useRef, useEffect } from 'react';
import Info from '../assets/info.svg';
import PageIcon from '../assets/documentation.svg';
import EmailIcon from '../assets/envelope.svg';
import { useTranslation } from 'react-i18next';
const Help = () => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const { t } = useTranslation();

  const toggleDropdown = () => {
    setIsOpen((prev) => !prev);
  };

  const handleClickOutside = (event: MouseEvent) => {
    if (
      dropdownRef.current &&
      !dropdownRef.current.contains(event.target as Node) &&
      buttonRef.current &&
      !buttonRef.current.contains(event.target as Node)
    ) {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <div className="relative inline-block text-sm" ref={dropdownRef}>
      <button
        ref={buttonRef}
        onClick={toggleDropdown}
        className="my-auto mx-4 w-full flex items-center h-9 gap-4 rounded-3xl hover:bg-gray-100 dark:hover:bg-[#28292E]"
      >
        <img src={Info} alt="info" className="ml-2 w-5 filter dark:invert" />
        {t('help')}
      </button>
      {isOpen && (
        <div
          className={`absolute translate-x-4 -translate-y-28 z-10 w-48 shadow-lg bg-white dark:bg-[#444654] rounded-xl`}
        >
          <a
            href="https://docs.docsgpt.cloud/"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start gap-4 px-4 py-2 text-black dark:text-white hover:bg-bright-gray dark:hover:bg-[#545561] rounded-t-xl"
          >
            <img
              src={PageIcon}
              alt="Documentation"
              className="filter dark:invert"
              width={20}
            />
            {t('documentation')}
          </a>
          <a
            href="mailto:contact@arc53.com"
            className="flex items-start gap-4 px-4 py-2 text-black dark:text-white hover:bg-bright-gray dark:hover:bg-[#545561] rounded-b-xl"
          >
            <img
              src={EmailIcon}
              alt="Email Us"
              className="filter dark:invert p-0.5"
              width={20}
            />
            {t('emailUs')}
          </a>
        </div>
      )}
    </div>
  );
};

export default Help;
