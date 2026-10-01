import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { IconButton } from '@/components/ui/icon-button';
import { cn } from '@/lib/utils';

const alertVariants = cva(
  // The icon has its own 16px column and sits centred on the text block
  // (spanning a title and its description); everything else goes in the
  // text column. The icon takes the text colour, so the two always match.
  'relative grid w-full grid-cols-[0_1fr] gap-y-1 rounded-xl border px-4 py-3 text-sm has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] has-[>svg]:gap-x-3 [&>svg]:size-4 [&>svg]:self-center [&>svg]:text-current has-[>[data-slot=alert-title]]:[&>svg]:row-span-2 [&>:not(svg)]:col-start-2',
  {
    variants: {
      variant: {
        destructive: 'border-destructive/50 bg-destructive/10 text-destructive',
        success: 'border-success/50 bg-success/10 text-success',
        warning: 'border-warning/50 bg-warning/10 text-warning',
        info: 'border-info/50 bg-info/10 text-info',
      },
    },
  },
);

type AlertIcon = React.ComponentType<React.SVGProps<SVGSVGElement>>;
type AlertVariant = NonNullable<VariantProps<typeof alertVariants>['variant']>;

/** The icon each variant draws unless `icon` overrides it. */
const alertIcons: Record<AlertVariant, AlertIcon> = {
  destructive: CircleAlert,
  warning: TriangleAlert,
  success: CircleCheck,
  info: Info,
};

type AlertProps = React.ComponentProps<'div'> & {
  /** The status: there is no quiet default, so every notice picks one. */
  variant: AlertVariant;
  /**
   * The leading icon. Unset draws the variant's own (destructive
   * CircleAlert, warning TriangleAlert, success CircleCheck, info Info);
   * a component replaces it; `null` drops it. Never pass an icon as a
   * child.
   */
  icon?: AlertIcon | null;
  /**
   * Adds a ghost X in the top-right corner (a notice floating over a
   * canvas) and pads the text clear of it. Needs a TooltipProvider above.
   */
  onClose?: () => void;
};

function Alert({
  className,
  variant,
  icon,
  onClose,
  children,
  ...props
}: AlertProps) {
  const { t } = useTranslation();
  const Icon = icon === undefined ? alertIcons[variant] : icon;
  return (
    <div
      data-slot="alert"
      data-variant={variant}
      // A success notice confirms rather than interrupts, so it is polite.
      role={variant === 'success' ? 'status' : 'alert'}
      className={cn(alertVariants({ variant }), onClose && 'pr-10', className)}
      {...props}
    >
      {Icon ? <Icon data-slot="alert-icon" aria-hidden="true" /> : null}
      {children}
      {onClose ? (
        <div data-slot="alert-close" className="absolute top-2.5 right-2.5">
          <IconButton
            variant="ghost"
            size="icon-xs"
            onClick={onClose}
            label={t('close')}
            icon={X}
          />
        </div>
      ) : null}
    </div>
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<'h5'>) {
  return (
    <h5
      data-slot="alert-title"
      className={cn('leading-none font-medium tracking-tight', className)}
      {...props}
    />
  );
}

function AlertDescription({
  className,
  ...props
}: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="alert-description"
      className={cn('text-sm [&_p]:leading-relaxed', className)}
      {...props}
    />
  );
}

export { Alert, AlertTitle, AlertDescription };
export type { AlertProps };
