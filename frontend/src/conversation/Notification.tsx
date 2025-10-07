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
  return (
    <a
      className="absolute top-20 right-4 z-20 flex w-2/3 items-center justify-center gap-2 rounded-lg bg-cover bg-center bg-no-repeat px-2 py-4 md:w-1/3 lg:top-16 lg:w-1/4 2xl:w-1/5"
      style={{ backgroundImage: `url(${bg})` }}
      href={notificationLink}
      target="_blank"
      aria-label="Notification"
      rel="noreferrer"
    >
      <p className="text-white-3000 text-[10px] font-semibold xl:text-sm">
        {notificationText}
      </p>
      <span>
        <img className="w-full" src={rightArrow} alt="Right Arrow" />
      </span>

      <button
        className="absolute top-1.5 right-1.5 z-30 h-4 w-4 hover:opacity-70"
        aria-label="Close notification"
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
