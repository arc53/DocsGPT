export function formatDate(dateString: string): string {
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(dateString)) {
    // ISO 8601 format
    const dateTime = new Date(dateString);
    return dateTime.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } else if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(dateString)) {
    const dateTime = new Date(dateString);
    return dateTime.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } else if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(dateString)) {
    const dateTime = new Date(dateString);
    return dateTime.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
    // `new Date('YYYY-MM-DD')` parses as UTC midnight, so rendering it
    // in a timezone west of UTC shows the previous day. Construct from
    // parts so the date is interpreted in local time (matching the
    // space-separated hourly buckets, which already parse as local).
    const [year, month, day] = dateString.split('-').map(Number);
    const date = new Date(year, month - 1, day);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } else if (
    /^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(
      dateString,
    )
  ) {
    // Format: "Fri, 08 Jul 2025 06:00:00 GMT"
    const dateTime = new Date(dateString);
    return dateTime.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } else {
    return dateString;
  }
}
