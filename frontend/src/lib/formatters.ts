import { parseISO, format, differenceInSeconds, differenceInMinutes, differenceInHours, differenceInDays } from 'date-fns';

function toDate(timestamp: string | Date | null | undefined): Date | null {
  if (!timestamp) return null;
  if (timestamp instanceof Date) return isNaN(timestamp.getTime()) ? null : timestamp;
  try {
    const date = parseISO(timestamp);
    return isNaN(date.getTime()) ? null : date;
  } catch {
    return null;
  }
}

/**
 * Format a timestamp using locale-aware date+time format.
 * @param timestamp - ISO timestamp string or Date object
 * @returns Formatted date/time string or 'N/A' if invalid
 */
export function formatTimestamp(timestamp: string | Date | null | undefined): string {
  const date = toDate(timestamp);
  if (!date) return 'N/A';
  return format(date, 'PPpp');
}

/**
 * Format a timestamp as a locale-aware date only (e.g., "Jun 15, 2024").
 * @param timestamp - ISO timestamp string or Date object
 * @returns Formatted date string or 'N/A' if invalid
 */
export function formatDateOnly(timestamp: string | Date | null | undefined): string {
  const date = toDate(timestamp);
  if (!date) return 'N/A';
  return format(date, 'PP');
}

/**
 * Format a timestamp as a locale-aware time only (e.g., "2:30:00 PM").
 * @param timestamp - ISO timestamp string or Date object
 * @returns Formatted time string or 'N/A' if invalid
 */
export function formatTimeOnly(timestamp: string | Date | null | undefined): string {
  const date = toDate(timestamp);
  if (!date) return 'N/A';
  return format(date, 'pp');
}

/**
 * Format a duration in seconds to human-readable string.
 * @param seconds - Duration in seconds (can be fractional)
 * @returns Human-readable duration (e.g., "1.5s", "2m 30s", "1h 5m")
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'N/A';
  if (seconds < 0) return 'N/A';

  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  }

  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

/**
 * Format duration between two timestamps.
 * @param startDate - Start timestamp
 * @param endDate - End timestamp
 * @returns Human-readable duration
 */
export function formatDurationBetween(
  startDate: string | Date | null | undefined,
  endDate: string | Date | null | undefined
): string {
  const start = toDate(startDate);
  const end = toDate(endDate);
  if (!start || !end) return 'N/A';

  const durationMs = end.getTime() - start.getTime();
  if (durationMs < 0) return 'N/A';

  return formatDuration(durationMs / 1000);
}

/**
 * Format a timestamp as relative time (e.g., "just now", "5m ago", "2h ago").
 * Falls back to date string for timestamps older than 7 days.
 * @param timestamp - ISO timestamp string or Date object
 * @returns Relative time string
 */
export function formatRelativeTime(timestamp: string | Date | null | undefined): string {
  const date = toDate(timestamp);
  if (!date) return 'N/A';

  const now = new Date();

  if (date > now) return format(date, 'PP');

  const diffSecs = differenceInSeconds(now, date);
  const diffMins = differenceInMinutes(now, date);
  const diffHrs = differenceInHours(now, date);
  const diffDys = differenceInDays(now, date);

  if (diffSecs < 60) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHrs < 24) return `${diffHrs}h ago`;
  if (diffDys < 7) return `${diffDys}d ago`;

  return format(date, 'PP');
}

/**
 * Truncate a string to a maximum length with ellipsis.
 * @param str - String to truncate
 * @param maxLength - Maximum length (default: 50)
 * @returns Truncated string
 */
export function truncate(str: string | null | undefined, maxLength = 50): string {
  if (!str) return '';
  if (str.length <= maxLength) return str;
  return `${str.slice(0, maxLength - 3)}...`;
}
