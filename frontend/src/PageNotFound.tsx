import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export default function PageNotFound() {
  const { t } = useTranslation();

  return (
    <div className="bg-background grid min-h-screen">
      <div className="text-foreground bg-muted mx-auto my-auto mt-20 flex w-full max-w-6xl flex-col place-items-center gap-6 rounded-3xl p-6 lg:p-10 xl:p-16">
        <h1 className="text-3xl">{t('pageNotFound.title')}</h1>
        <p>{t('pageNotFound.message')}</p>
        <Link
          to="/"
          className="bg-primary hover:bg-primary/90 text-primary-foreground mr-4 inline-flex cursor-pointer items-center justify-center rounded-full px-4 py-2 transition-colors duration-100"
        >
          {t('pageNotFound.goHome')}
        </Link>
      </div>
    </div>
  );
}
