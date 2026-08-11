import { useState, useRef, useEffect } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import Info from '../assets/info.svg';
import PageIcon from '../assets/documentation.svg';
import EmailIcon from '../assets/envelope.svg';
import { useTranslation } from 'react-i18next';
import { selectIsAdmin } from '../preferences/preferenceSlice';
import { Button } from './ui/button';
const Help = () => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const { t } = useTranslation();
  const isAdmin = useSelector(selectIsAdmin);

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
      <Button
        type="button"
        variant="ghost"
        ref={buttonRef}
        onClick={toggleDropdown}
        className="hover:bg-sidebar-accent mx-4 my-auto w-full justify-start gap-2.5 rounded-3xl pr-0 pl-3"
      >
        <img
          src={Info}
          alt="info"
          className="w-5 shrink-0 filter dark:invert"
        />
        {t('help')}
      </Button>
      {isOpen && (
        <div
          className={`dark:bg-card bg-card absolute z-10 w-48 translate-x-4 ${
            isAdmin ? '-translate-y-40' : '-translate-y-28'
          } rounded-xl shadow-lg`}
        >
          {isAdmin && (
            <Link
              to="/admin"
              onClick={() => setIsOpen(false)}
              className="hover:bg-muted text-foreground flex items-center gap-4 rounded-t-xl px-4 py-2"
            >
              <ShieldCheck
                size={20}
                strokeWidth={1.75}
                className="text-muted-foreground shrink-0"
              />
              {t('admin.label', 'Admin')}
            </Link>
          )}
          <a
            href="https://docs.docsgpt.cloud/"
            target="_blank"
            rel="noopener noreferrer"
            className={`hover:bg-muted text-foreground flex items-start gap-4 px-4 py-2 ${
              isAdmin ? '' : 'rounded-t-xl'
            }`}
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
            className="hover:bg-muted text-foreground flex items-start gap-4 rounded-b-xl px-4 py-2"
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
