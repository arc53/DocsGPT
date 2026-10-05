import { FileText, Info, Mail, ShieldCheck } from 'lucide-react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { selectIsAdmin } from '../preferences/preferenceSlice';
import { Button } from './ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';

const Help = () => {
  const { t } = useTranslation();
  const isAdmin = useSelector(selectIsAdmin);

  return (
    <div className="inline-block text-sm">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="sidebar-item"
            className="mx-4 my-auto w-full"
          >
            <Info className="text-muted-foreground size-5 shrink-0" />
            {t('help')}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-48">
          {isAdmin && (
            <DropdownMenuItem asChild>
              <Link to="/admin">
                <ShieldCheck />
                {t('admin.label', 'Admin')}
              </Link>
            </DropdownMenuItem>
          )}
          <DropdownMenuItem asChild>
            <a
              href="https://docs.docsgpt.cloud/"
              target="_blank"
              rel="noopener noreferrer"
            >
              <FileText />
              {t('documentation')}
            </a>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <a href="mailto:support@docsgpt.cloud">
              <Mail />
              {t('emailUs')}
            </a>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};

export default Help;
