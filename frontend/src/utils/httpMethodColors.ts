const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-[#D1FAE5] text-[#065F46] dark:bg-[#064E3B]/60 dark:text-[#6EE7B7]',
  POST: 'bg-[#DBEAFE] text-[#1E40AF] dark:bg-[#1E3A8A]/60 dark:text-[#93C5FD]',
  PUT: 'bg-[#FEF3C7] text-[#92400E] dark:bg-[#78350F]/60 dark:text-[#FCD34D]',
  DELETE:
    'bg-[#FEE2E2] text-[#991B1B] dark:bg-[#7F1D1D]/60 dark:text-[#FCA5A5]',
  PATCH: 'bg-[#EDE9FE] text-[#5B21B6] dark:bg-[#4C1D95]/60 dark:text-[#C4B5FD]',
  HEAD: 'bg-[#F3F4F6] text-[#374151] dark:bg-[#374151]/60 dark:text-[#D1D5DB]',
  OPTIONS:
    'bg-[#F3F4F6] text-[#374151] dark:bg-[#374151]/60 dark:text-[#D1D5DB]',
};

export function getMethodColorClass(method: string): string {
  return METHOD_COLORS[method.toUpperCase()] ?? METHOD_COLORS.GET;
}
