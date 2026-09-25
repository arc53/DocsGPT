import { useState, useRef, useEffect } from 'react';
import { Info, Mail, ShieldCheck } from 'lucide-react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import PageIcon from '../assets/documentation.svg';
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
        variant="sidebar-item"
        ref={buttonRef}
        onClick={toggleDropdown}
        className="mx-4 my-auto w-full"
      >
        <Info className="text-muted-foreground size-5 shrink-0" />
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
            <Mail className="size-5 shrink-0" />
            {t('emailUs')}
          </a>
        </div>
      )}
    </div>
  );
};

export default Help;
