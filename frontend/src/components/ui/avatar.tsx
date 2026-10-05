import * as React from 'react';
import { useEffect, useState } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import Robot from '@/assets/robot.svg';
import { cn } from '@/lib/utils';

// Hoisted so the /design gallery can list the keys cva uses.
const avatarVariantOptions = {
  // `none` keeps the historical behaviour where the image sets the size.
  // The rest share Button's names at Button's heights (xs 28, sm 32,
  // default 36, lg 40), so an avatar beside a button reads one scale.
  size: {
    none: '',
    xs: 'flex size-7 items-center justify-center overflow-hidden text-xs',
    sm: 'flex size-8 items-center justify-center overflow-hidden text-sm',
    default: 'flex size-9 items-center justify-center overflow-hidden text-sm',
    lg: 'flex size-10 items-center justify-center overflow-hidden text-base',
    // A 48px tile: the connector logo leading a drawer or wizard header.
    xl: 'flex size-12 items-center justify-center overflow-hidden text-lg',
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
    // The icon tile: a muted square behind a size-4 icon, leading a ListRow
    // or a header. Pair with `shape="square"`.
    icon: 'bg-muted text-muted-foreground',
  },
};

const avatarVariants = cva('shrink-0', {
  variants: avatarVariantOptions,
  // The 48px square rounds with the radius of a larger surface.
  compoundVariants: [{ size: 'xl', shape: 'square', class: 'rounded-xl' }],
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

/** Every `size` key, in declaration order (`none` first). */
const avatarSizeNames = Object.keys(
  avatarVariantOptions.size,
) as (keyof typeof avatarVariantOptions.size)[];

export { Avatar, avatarSizeNames, avatarVariants };
