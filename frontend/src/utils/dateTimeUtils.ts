export function formatDate(dateString: string): string {
  try {
    const date = new Date(dateString);

    if (isNaN(date.getTime())) {
      throw new Error('Invalid date');
    }

    const userLocale = navigator.language || 'en-US';
    const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    const weekday = date.toLocaleDateString(userLocale, {
      weekday: 'short',
      timeZone: userTimezone,
    });

    const monthDay = date.toLocaleDateString(userLocale, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      timeZone: userTimezone,
    });

    const time = date
      .toLocaleTimeString(userLocale, {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZone: userTimezone,
      })
      .replace(/am|pm/i, (match) => match.toUpperCase());

    return `${weekday}, ${monthDay} ${time}`;
  } catch (error) {
    console.error('Error formatting date:', error);
    return dateString;
  }
}
