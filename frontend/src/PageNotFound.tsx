import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';

export default function PageNotFound() {
  const { t } = useTranslation();

  return (
    <div className="bg-background grid min-h-dvh">
      <div className="text-foreground bg-muted mx-auto my-auto mt-20 flex w-full max-w-6xl flex-col place-items-center gap-6 rounded-3xl p-6 lg:p-10 xl:p-16">
        <h1 className="text-3xl">{t('pageNotFound.title')}</h1>
        <p>{t('pageNotFound.message')}</p>
        <Button asChild size="lg" shape="pill">
          <Link to="/">{t('pageNotFound.goHome')}</Link>
        </Button>
      </div>
    </div>
  );
}
