/**
 * Format a timestamp as a localized date string (DD/MM/YYYY HH:mm).
 * @param timestamp - ISO timestamp string or Date object
 * @returns Formatted date string or 'N/A' if invalid
 */
export function formatDate(timestamp: string | Date | null | undefined): string {
  if (!timestamp) return 'N/A';

  const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
  if (isNaN(date.getTime())) return 'N/A';

  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');

  return `${day}/${month}/${year} ${hours}:${minutes}`;
}

/**
 * Format a timestamp using the browser's locale settings.
 * @param timestamp - ISO timestamp string or Date object
 * @param options - Intl.DateTimeFormat options
 * @returns Localized date/time string
 */
export function formatTimestamp(
  timestamp: string | Date | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  if (!timestamp) return 'N/A';

  const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
  if (isNaN(date.getTime())) return 'N/A';

  return date.toLocaleString(undefined, options);
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
  if (!startDate || !endDate) return 'N/A';

  const start = startDate instanceof Date ? startDate : new Date(startDate);
  const end = endDate instanceof Date ? endDate : new Date(endDate);

  if (isNaN(start.getTime()) || isNaN(end.getTime())) return 'N/A';

  const durationMs = end.getTime() - start.getTime();
  if (durationMs < 0) return 'N/A';

  return formatDuration(durationMs / 1000);
}

/**
 * Format a timestamp as relative time (e.g., "just now", "5m ago", "2h ago").
 * Falls back to date string for timestamps older than 24 hours.
 * @param timestamp - ISO timestamp string or Date object
 * @returns Relative time string
 */
export function formatRelativeTime(timestamp: string | Date | null | undefined): string {
  if (!timestamp) return 'N/A';

  const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
  if (isNaN(date.getTime())) return 'N/A';

  const now = Date.now();
  const diffMs = now - date.getTime();

  // Future dates
  if (diffMs < 0) return date.toLocaleDateString();

  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString();
}

/**
 * Format bytes to human-readable size.
 * @param bytes - Size in bytes
 * @param decimals - Number of decimal places (default: 2)
 * @returns Human-readable size (e.g., "1.5 KB", "2.3 MB")
 */
export function formatBytes(bytes: number | null | undefined, decimals = 2): string {
  if (bytes === null || bytes === undefined || bytes < 0) return 'N/A';
  if (bytes === 0) return '0 B';

  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(decimals))} ${sizes[i]}`;
}

/**
 * Format a number with thousand separators.
 * @param value - Number to format
 * @returns Formatted number string
 */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'N/A';
  return value.toLocaleString();
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
