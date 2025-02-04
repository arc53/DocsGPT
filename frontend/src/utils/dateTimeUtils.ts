export function formatDate(dateString: string): string {
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(dateString)) {
    const dateTime = new Date(dateString);
    return dateTime.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  } else if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(dateString)) {
    const dateTime = new Date(dateString);
    return dateTime.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } else {
    return dateString;
  }
}
