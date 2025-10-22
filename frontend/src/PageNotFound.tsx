import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export default function PageNotFound() {
  const { t } = useTranslation();

  return (
    <div className="dark:bg-raisin-black grid min-h-screen">
      <p className="text-jet dark:bg-outer-space mx-auto my-auto mt-20 flex w-full max-w-6xl flex-col place-items-center gap-6 rounded-3xl bg-gray-100 p-6 lg:p-10 xl:p-16 dark:text-gray-100">
        <h1>{t('pageNotFound.title')}</h1>
        <p>{t('pageNotFound.message')}</p>
        <button className="pointer-cursor bg-blue-1000 hover:bg-blue-3000 mr-4 flex cursor-pointer items-center justify-center rounded-full px-4 py-2 text-white transition-colors duration-100">
          <Link to="/">{t('pageNotFound.goHome')}</Link>
        </button>
      </p>
    </div>
  );
}
