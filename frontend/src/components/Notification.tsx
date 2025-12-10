import { useTranslation } from 'react-i18next';
import close from '../assets/cross.svg';

interface NotificationProps {
  notificationText: string;
  notificationLink: string;
  handleCloseNotification: () => void;
}

const stars = Array.from({ length: 12 }, (_, i) => ({
  id: i,
  size: Math.random() * 2 + 1, // 1-3px
  left: Math.random() * 100, // 0-100%
  top: Math.random() * 100, // 0-100%
  animationDuration: Math.random() * 3 + 2, // 2-5s
  animationDelay: Math.random() * 2, // 0-2s
  opacity: Math.random() * 0.5 + 0.3, // 0.3-0.8
}));

export default function Notification({
  notificationText,
  notificationLink,
  handleCloseNotification,
}: NotificationProps) {
  const { t } = useTranslation();
  return (
    <>
      <style>{`
        @keyframes twinkle {
          0%, 100% {
            opacity: 0.3;
            transform: scale(1) translateY(0);
          }
          50% {
            opacity: 1;
            transform: scale(1.2) translateY(-2px);
          }
        }

        .star {
          animation: twinkle var(--duration) ease-in-out infinite;
          animation-delay: var(--delay);
        }
      `}</style>
      <a
        className="group absolute right-2 bottom-6 z-20 flex w-3/4 items-center justify-center gap-2 overflow-hidden rounded-lg px-2 py-4 sm:right-4 md:w-2/5 lg:w-1/3 xl:w-1/4 2xl:w-1/5"
        style={{
          background:
            'linear-gradient(90deg, #390086 0%, #6222B7 100%), linear-gradient(90deg, rgba(57, 0, 134, 0) 0%, #6222B7 53.02%, rgba(57, 0, 134, 0) 100%)',
        }}
        href={notificationLink}
        target="_blank"
        aria-label={t('notification.ariaLabel')}
        rel="noreferrer"
      >
        {/* Animated stars background */}
        <div className="pointer-events-none absolute inset-0">
          {stars.map((star) => (
            <svg
              key={star.id}
              className="star absolute"
              style={
                {
                  width: `${star.size * 4}px`,
                  height: `${star.size * 4}px`,
                  left: `${star.left}%`,
                  top: `${star.top}%`,
                  opacity: star.opacity,
                  filter: `drop-shadow(0 0 ${star.size}px rgba(255, 255, 255, 0.5))`,
                  '--duration': `${star.animationDuration}s`,
                  '--delay': `${star.animationDelay}s`,
                } as React.CSSProperties & {
                  '--duration': string;
                  '--delay': string;
                }
              }
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* 4-pointed Christmas star */}
              <path
                d="M12 0L13.5 10.5L24 12L13.5 13.5L12 24L10.5 13.5L0 12L10.5 10.5L12 0Z"
                fill="white"
              />
            </svg>
          ))}
        </div>

        <p className="text-white-3000 relative z-10 text-xs leading-6 font-semibold xl:text-sm xl:leading-7">
          {notificationText}
        </p>
        <span className="relative z-10 flex items-center">
          <svg
            width="18"
            height="13"
            viewBox="0 0 18 13"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="overflow-visible"
          >
            {/* Arrow tail - grows leftward from arrow head's back point on hover */}
            <rect
              x="4"
              y="5.75"
              width="8"
              height="1.5"
              fill="white"
              className="scale-x-0 transition-transform duration-300 ease-out group-hover:scale-x-100"
              style={{ transformOrigin: '12px 6.5px' }}
            />
            {/* Arrow head - pushed forward by the tail on hover */}
            <path
              d="M13.0303 7.03033C13.3232 6.73744 13.3232 6.26256 13.0303 5.96967L8.25736 1.1967C7.96447 0.903806 7.48959 0.903806 7.1967 1.1967C6.90381 1.48959 6.90381 1.96447 7.1967 2.25736L11.4393 6.5L7.1967 10.7426C6.90381 11.0355 6.90381 11.5104 7.1967 11.8033C7.48959 12.0962 7.96447 12.0962 8.25736 11.8033L13.0303 7.03033Z"
              fill="white"
              className="transition-transform duration-300 ease-out group-hover:translate-x-1"
            />
          </svg>
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
    </>
  );
}
