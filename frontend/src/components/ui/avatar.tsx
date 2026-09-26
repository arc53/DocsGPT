import * as React from 'react';
import { useEffect, useState } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import Robot from '@/assets/robot.svg';
import { cn } from '@/lib/utils';

const avatarVariants = cva('shrink-0', {
  variants: {
    // `none` keeps the historical behaviour where the image sets the size.
    // The rest share Button's names at Button's heights (xs 28, sm 32,
    // default 36, lg 40), so an avatar beside a button reads one scale.
    size: {
      none: '',
      xs: 'flex size-7 items-center justify-center overflow-hidden text-xs',
      sm: 'flex size-8 items-center justify-center overflow-hidden text-sm',
      default:
        'flex size-9 items-center justify-center overflow-hidden text-sm',
      lg: 'flex size-10 items-center justify-center overflow-hidden text-base',
    },
    shape: {
      none: '',
      circle: 'rounded-full',
      square: 'rounded-md',
    },
    // Background for initials or icon fallbacks rendered via `children`.
    variant: {
      default: '',
      primary: 'bg-secondary text-secondary-foreground font-medium',
      muted: 'bg-muted-foreground/15 text-foreground font-medium',
    },
  },
  defaultVariants: {
    size: 'none',
    shape: 'none',
    variant: 'default',
  },
});

type AvatarProps = React.ComponentProps<'div'> &
  VariantProps<typeof avatarVariants> & {
    src?: string | null;
    alt?: string;
    fallbackSrc?: string;
    imgClassName?: string;
  };

function Avatar({
  src,
  alt = 'agent',
  fallbackSrc = Robot,
  className,
  imgClassName,
  children,
  size = 'none',
  shape = 'none',
  variant = 'default',
  ...props
}: AvatarProps) {
  const resolvedSrc = src && src.trim() !== '' ? src : fallbackSrc;
  const [currentSrc, setCurrentSrc] = useState(resolvedSrc);

  useEffect(() => {
    const newSrc = src && src.trim() !== '' ? src : fallbackSrc;
    if (newSrc !== currentSrc) {
      setCurrentSrc(newSrc);
    }
  }, [src, fallbackSrc]);

  return (
    <div
      data-slot="avatar"
      data-size={size}
      data-shape={shape}
      data-variant={variant}
      className={cn(avatarVariants({ size, shape, variant }), className)}
      {...props}
    >
      {children ?? (
        <img
          src={currentSrc}
          alt={alt}
          className={imgClassName}
          referrerPolicy="no-referrer"
          crossOrigin="anonymous"
          onError={() => {
            if (currentSrc !== fallbackSrc) setCurrentSrc(fallbackSrc);
          }}
        />
      )}
    </div>
  );
}

export { Avatar, avatarVariants };
