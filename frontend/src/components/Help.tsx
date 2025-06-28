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
        className="mx-4 my-auto flex h-9 w-full items-center gap-4 rounded-3xl hover:bg-gray-100 dark:hover:bg-[#28292E]"
      >
        <img src={Info} alt="info" className="ml-2 w-5 filter dark:invert" />
        {t('help')}
      </button>
      {isOpen && (
        <div
          className={`dark:bg-outer-space absolute z-10 w-48 translate-x-4 -translate-y-28 rounded-xl bg-white shadow-lg`}
        >
          <a
            href="https://docs.docsgpt.cloud/"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:bg-bright-gray flex items-start gap-4 rounded-t-xl px-4 py-2 text-black dark:text-white dark:hover:bg-[#545561]"
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
            href="mailto:support@docsgpt.cloud"
            className="hover:bg-bright-gray flex items-start gap-4 rounded-b-xl px-4 py-2 text-black dark:text-white dark:hover:bg-[#545561]"
          >
            <img
              src={EmailIcon}
              alt="Email Us"
              className="p-0.5 filter dark:invert"
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
