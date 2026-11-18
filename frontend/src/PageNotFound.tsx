import { MapPinOff } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * Any unknown URL. It renders outside the app shell, so it fills the
 * screen itself (min-h-dvh) and draws the page-level EmptyState.
 */
export default function PageNotFound() {
  const { t } = useTranslation();

  return (
    <main className="bg-background flex min-h-dvh flex-col justify-center p-4">
      <EmptyState
        icon={MapPinOff}
        titleAs="h1"
        title={t('pageNotFound.title')}
        description={t('pageNotFound.message')}
        action={
          <Button asChild shape="pill">
            <Link to="/">{t('pageNotFound.goHome')}</Link>
          </Button>
        }
      />
    </main>
  );
}
