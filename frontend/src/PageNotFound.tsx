import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export default function PageNotFound() {
  const { t } = useTranslation();

  return (
    <div className="bg-background grid min-h-screen">
      <p className="text-foreground dark:bg-card mx-auto my-auto mt-20 flex w-full max-w-6xl flex-col place-items-center gap-6 rounded-3xl bg-gray-100 p-6 lg:p-10 xl:p-16">
        <h1>{t('pageNotFound.title')}</h1>
        <p>{t('pageNotFound.message')}</p>
        <Link
          to="/"
          className="bg-primary hover:bg-primary/90 mr-4 inline-flex cursor-pointer items-center justify-center rounded-full px-4 py-2 text-white transition-colors duration-100"
        >
          {t('pageNotFound.goHome')}
        </Link>
      </p>
    </div>
  );
}
