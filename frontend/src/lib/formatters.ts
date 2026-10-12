import { differenceInSeconds, differenceInMinutes, differenceInHours, differenceInDays } from 'date-fns';

function validDate(timestamp: string | null | undefined): Date | null {
    const date = timestamp ? new Date(timestamp) : null;
    return date && !isNaN(date.getTime()) ? date : null;
}

/**
 * Format a timestamp using the browser's locale (date + time).
 * @param timestamp - The ISO time from the API
 * @returns Formatted date/time string or 'N/A' if invalid
 */
export function formatTimestamp(timestamp: string | null | undefined): string {
    const date = validDate(timestamp);
    if (!date) return 'N/A';
    return date.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

/**
 * Format a timestamp as a locale-aware date only (e.g., "Jun 15, 2024").
 * @param timestamp - The ISO time from the API
 * @returns Formatted date string or 'N/A' if invalid
 */
export function formatDateOnly(timestamp: string | null | undefined): string {
    const date = validDate(timestamp);
    if (!date) return 'N/A';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/**
 * Format a timestamp as a locale-aware time only (e.g., "2:30:00 PM").
 * @param timestamp - The ISO time from the API
 * @returns Formatted time string or 'N/A' if invalid
 */
export function formatTimeOnly(timestamp: string | null | undefined): string {
    const date = validDate(timestamp);
    if (!date) return 'N/A';
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
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
    startDate: string | null | undefined,
    endDate: string | null | undefined,
): string {
    const start = validDate(startDate);
    const end = validDate(endDate);
    if (!start || !end) return 'N/A';

    const durationMs = end.getTime() - start.getTime();
    if (durationMs < 0) return 'N/A';

    return formatDuration(durationMs / 1000);
}

/**
 * Format a timestamp as relative time (e.g., "just now", "5m ago", "2h ago").
 * Falls back to date string for timestamps older than 7 days.
 * @param timestamp - The ISO time from the API
 * @returns Relative time string
 */
export function formatRelativeTime(timestamp: string | null | undefined): string {
    const date = validDate(timestamp);
    if (!date) return 'N/A';

    const now = new Date();

    if (date > now) return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });

    const diffSecs = differenceInSeconds(now, date);
    const diffMins = differenceInMinutes(now, date);
    const diffHrs = differenceInHours(now, date);
    const diffDys = differenceInDays(now, date);

    if (diffSecs < 60) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHrs < 24) return `${diffHrs}h ago`;
    if (diffDys < 7) return `${diffDys}d ago`;

    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
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

/**
 * The one way a boolean field reads in the UI.
 * @param value - The field's value
 * @returns "Yes" or "No"
 */
export function formatBoolean(value: boolean): string {
    return value ? 'Yes' : 'No';
}

/**
 * The one label for an API field: its key, titled the way Pydantic titles it in the spec (`created_at` is "Created At").
 * @param key - The field's key in the API
 * @returns The label
 */
export function fieldTitle(key: string): string {
    return key
        .replace(/[a-z]+/gi, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .replaceAll('_', ' ');
}
