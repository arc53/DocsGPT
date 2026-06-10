import { LogOut } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import useTokenAuth from '../hooks/useTokenAuth';
import { Avatar } from './ui/avatar';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';

/**
 * Top-right account menu for OIDC sessions: an avatar that opens a popover
 * showing the signed-in name/email and a sign-out action. Renders nothing for
 * other auth modes, which carry no user identity.
 */
export default function ProfileButton() {
  const { t } = useTranslation();
  const { authType, userName, userEmail, userPicture, logout } = useTokenAuth();

  if (authType !== 'oidc' || (!userName && !userEmail)) return null;

  const initial = (userName || userEmail || '?').charAt(0).toUpperCase();
  const renderAvatar = (size: string, text: string) =>
    userPicture ? (
      <Avatar
        src={userPicture}
        alt={userName || userEmail || 'User avatar'}
        className={size}
        imgClassName={`${size} rounded-full object-cover`}
      />
    ) : (
      <Avatar className={size}>
        <span
          className={`bg-primary text-primary-foreground flex ${size} items-center justify-center rounded-full ${text} font-medium`}
        >
          {initial}
        </span>
      </Avatar>
    );

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t('auth.account')}
          className="ring-offset-background focus-visible:ring-ring hover:ring-primary/40 rounded-full transition outline-none hover:ring-2 hover:ring-offset-2 focus-visible:ring-2 focus-visible:ring-offset-2"
        >
          {renderAvatar('size-8', 'text-sm')}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-64 p-0">
        <div className="flex items-center gap-3 p-4">
          {renderAvatar('size-10', 'text-base')}
          <span className="flex min-w-0 flex-col">
            {userName && (
              <p className="text-foreground truncate text-sm font-medium dark:text-white">
                {userName}
              </p>
            )}
            {userEmail && (
              <p className="text-muted-foreground truncate text-xs">
                {userEmail}
              </p>
            )}
          </span>
        </div>
        <div className="dark:border-sidebar-border border-t" />
        <div className="p-1">
          <button
            type="button"
            onClick={logout}
            data-testid="oidc-signout"
            className="text-foreground hover:bg-sidebar-accent flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm dark:text-white"
          >
            <LogOut
              className="text-muted-foreground size-4 shrink-0"
              strokeWidth={1.75}
            />
            {t('auth.signOut')}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
