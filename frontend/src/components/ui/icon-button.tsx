import * as React from 'react';
import type { VariantProps } from 'class-variance-authority';

import { Button, buttonVariants } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

type IconButtonProps = Omit<
  React.ComponentProps<typeof Button>,
  'aria-label' | 'title' | 'size'
> & {
  /** The accessible name, and the tooltip text unless `hint` is set. */
  label: string;
  /** A lucide (or svg component) icon, rendered aria-hidden. */
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  /** Tooltip text when it differs from the name ("Undo (Ctrl+Z)"). */
  hint?: React.ReactNode;
  /** Tooltip side: `bottom` for header buttons, `top` (default) under text. */
  side?: React.ComponentProps<typeof TooltipContent>['side'];
  size?: Extract<
    VariantProps<typeof buttonVariants>['size'],
    'icon' | 'icon-xs' | 'icon-sm' | 'icon-lg'
  >;
};

/**
 * An icon-only Button with its name and tooltip in one prop. It never sets
 * a native `title`. Pass `children` instead of `icon` for a custom glyph
 * (a spinner, an asset svg); the button stays `aria-label`-named.
 */
function IconButton({
  label,
  icon: Icon,
  hint,
  side,
  size = 'icon',
  type = 'button',
  children,
  ...props
}: IconButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button aria-label={label} size={size} type={type} {...props}>
          {children ?? (Icon ? <Icon aria-hidden="true" /> : null)}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={side}>{hint ?? label}</TooltipContent>
    </Tooltip>
  );
}

export { IconButton };
export type { IconButtonProps };
