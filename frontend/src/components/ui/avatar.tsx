import * as React from 'react';
import { useEffect, useState } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import Robot from '../../assets/robot.svg';
import { cn } from '@/lib/utils';

const avatarVariants = cva('shrink-0', {
  variants: {
    // `none` keeps the historical behaviour where the image sets the size.
    size: {
      none: '',
      sm: 'flex size-7 items-center justify-center overflow-hidden text-xs',
      default:
        'flex size-8 items-center justify-center overflow-hidden text-sm',
      lg: 'flex size-9 items-center justify-center overflow-hidden text-sm',
      xl: 'flex size-10 items-center justify-center overflow-hidden text-base',
    },
    shape: {
      none: '',
      circle: 'rounded-full',
      square: 'rounded-md',
    },
    // Background for initials or icon fallbacks rendered via `children`.
    variant: {
      default: '',
      primary: 'bg-primary/10 text-primary font-medium dark:bg-primary/20',
      muted: 'bg-muted-foreground/15 text-foreground font-medium',
    },
  },
  defaultVariants: {
    size: 'none',
    shape: 'none',
    variant: 'default',
  },
});

type AvatarProps = VariantProps<typeof avatarVariants> & {
  src?: string | null;
  alt?: string;
  fallbackSrc?: string;
  className?: string;
  imgClassName?: string;
  children?: React.ReactNode;
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
