import { useTranslation } from 'react-i18next';
import close from '../assets/cross.svg';
import rightArrow from '../assets/arrow-full-right.svg';
import bg from '../assets/notification-bg.jpg';

interface NotificationProps {
  notificationText: string;
  notificationLink: string;
  handleCloseNotification: () => void;
}

export default function Notification({
  notificationText,
  notificationLink,
  handleCloseNotification,
}: NotificationProps) {
  const { t } = useTranslation();
  return (
    <a
      className="absolute right-2 bottom-6 z-20 flex w-3/4 items-center justify-center gap-2 rounded-lg bg-cover bg-center bg-no-repeat px-2 py-4 sm:right-4 md:w-2/5 lg:w-1/3 xl:w-1/4 2xl:w-1/5"
      style={{ backgroundImage: `url(${bg})` }}
      href={notificationLink}
      target="_blank"
      aria-label={t('notification.ariaLabel')}
      rel="noreferrer"
    >
      <p className="text-white-3000 text-xs leading-6 font-semibold xl:text-sm xl:leading-7">
        {notificationText}
      </p>
      <span>
        <img className="w-full" src={rightArrow} alt="" />
      </span>

      <button
        className="absolute top-2 right-2 z-30 h-4 w-4 hover:opacity-70"
        aria-label={t('notification.closeAriaLabel')}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          handleCloseNotification();
        }}
      >
        <img className="w-full" src={close} alt="Close notification" />
      </button>
    </a>
  );
}
