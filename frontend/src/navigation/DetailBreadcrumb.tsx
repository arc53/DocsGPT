import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { cn } from '@/lib/utils';

type DetailBreadcrumbProps = {
  parentLabel: string;
  currentLabel: string;
  /** Returns to the list view; kept a callback because these detail views are
   *  component state rather than routes, and some guard unsaved changes. */
  onParentClick: () => void;
  className?: string;
};

/**
 * Trail for a detail view nested inside a section page (a tool's config, a
 * team). The section nav's back button always means "leave the section", so
 * going up one level is a breadcrumb here rather than a second back arrow.
 */
export default function DetailBreadcrumb({
  parentLabel,
  currentLabel,
  onParentClick,
  className,
}: DetailBreadcrumbProps) {
  return (
    <Breadcrumb className={cn('min-w-0', className)}>
      <BreadcrumbList className="flex-nowrap">
        <BreadcrumbItem>
          <BreadcrumbLink asChild>
            <button type="button" onClick={onParentClick}>
              {parentLabel}
            </button>
          </BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem className="min-w-0">
          <BreadcrumbPage
            title={currentLabel}
            className="max-w-[32ch] truncate"
          >
            {currentLabel}
          </BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
  );
}
