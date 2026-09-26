import { LogOut } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import useTokenAuth from '../hooks/useTokenAuth';
import { Avatar } from './ui/avatar';
import { Button } from './ui/button';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
import { Separator } from './ui/separator';

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
  // `sm` is size-8/text-sm, `lg` is size-10/text-base; the size variant
  // also brings the flex centring and the overflow-hidden that clips both the
  // photo and the initials to the circle.
  const renderAvatar = (size: 'sm' | 'lg') =>
    userPicture ? (
      <Avatar
        size={size}
        shape="circle"
        src={userPicture}
        alt={userName || userEmail || t('components.profile.avatarAlt')}
        imgClassName="size-full object-cover"
      />
    ) : (
      <Avatar size={size} shape="circle" variant="primary">
        {initial}
      </Avatar>
    );

  return (
    <Popover>
      <PopoverTrigger asChild>
        {/* inline + pill: the avatar sets the size and the Button brings
            only the round focus ring; ghost's hover fill sits under it. */}
        <Button
          type="button"
          variant="ghost"
          size="inline"
          shape="pill"
          aria-label={t('auth.account')}
        >
          {renderAvatar('sm')}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-64 p-0">
        <div className="flex items-center gap-3 p-4">
          {renderAvatar('lg')}
          <span className="flex min-w-0 flex-col">
            {userName && (
              <p className="text-foreground truncate text-sm font-medium">
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
        <Separator />
        <div className="p-1">
          <Button
            type="button"
            variant="ghost"
            onClick={logout}
            data-testid="oidc-signout"
            className="w-full justify-start"
          >
            <LogOut className="text-muted-foreground" aria-hidden />
            {t('auth.signOut')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
