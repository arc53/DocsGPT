import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * The frame every in-chat card for a paused tool call shares (the approval
 * card and the Connect card): a header row with the connector's logo, a
 * readable title ("GitHub · Create issue") and a state Badge, then an
 * optional body and the actions row. It never grows past the chat column:
 * the title truncates, the body wraps and the actions wrap.
 *
 * @param icon - The connector logo (or the tool's icon), 20px.
 * @param title - The call's name, one line.
 * @param meta - A muted one-line extra after the title (an arguments preview).
 * @param state - The call's state, a Badge.
 * @param children - The body: a sentence, the arguments well.
 * @param actions - The row of `xs` pill buttons.
 */
export default function ToolCallCard({
  icon,
  title,
  meta,
  state,
  children,
  actions,
  className,
  ...rest
}: {
  icon?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  state?: ReactNode;
  children?: ReactNode;
  actions: ReactNode;
  className?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, 'title'>) {
  return (
    <div
      className={cn(
        'border-border bg-muted mb-2 flex w-full min-w-0 flex-col gap-2 overflow-hidden rounded-2xl border px-4 py-3',
        className,
      )}
      {...rest}
    >
      <div className="flex min-w-0 items-center gap-2">
        {icon && (
          <span className="flex size-5 shrink-0 items-center justify-center">
            {icon}
          </span>
        )}
        <span
          className="min-w-0 truncate text-sm font-medium"
          title={typeof title === 'string' ? title : undefined}
        >
          {title}
        </span>
        <span className="min-w-0 flex-1">{meta}</span>
        {state && <span className="flex shrink-0">{state}</span>}
      </div>
      {children && (
        <div className="min-w-0 text-sm wrap-break-word">{children}</div>
      )}
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}
