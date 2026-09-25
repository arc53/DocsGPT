import { ChevronDownIcon } from 'lucide-react';
import * as React from 'react';

import { cn, focusRing } from '@/lib/utils';
import * as AccordionPrimitive from '@radix-ui/react-accordion';

function Accordion({
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Root>) {
  return <AccordionPrimitive.Root data-slot="accordion" {...props} />;
}

function AccordionItem({
  className,
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Item>) {
  return (
    <AccordionPrimitive.Item
      data-slot="accordion-item"
      className={cn('overflow-hidden', className)}
      {...props}
    />
  );
}

function AccordionTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Trigger>) {
  return (
    <AccordionPrimitive.Header className="flex">
      <AccordionPrimitive.Trigger
        data-slot="accordion-trigger"
        className={cn(
          `${focusRing} flex flex-1 items-center justify-between gap-4 px-4 py-3 text-left text-sm font-medium transition-all outline-none focus-visible:ring-inset disabled:pointer-events-none disabled:opacity-50 [&[data-state=open]>svg]:rotate-180`,
          className,
        )}
        {...props}
      >
        {children}
        <ChevronDownIcon
          className="text-muted-foreground h-5 w-5 shrink-0 transition-transform duration-200"
          aria-hidden="true"
        />
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
}

function AccordionContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Content>) {
  return (
    <AccordionPrimitive.Content
      data-slot="accordion-content"
      className="data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down overflow-hidden"
      {...props}
    >
      <div className={cn('px-4 pb-3', className)}>{children}</div>
    </AccordionPrimitive.Content>
  );
}

export { Accordion, AccordionItem, AccordionTrigger, AccordionContent };
