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
    const date = new Date(dateString);
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
      weekday: 'short',
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
