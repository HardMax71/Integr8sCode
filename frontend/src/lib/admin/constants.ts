/**
 * Shared constants for admin pages
 */

// Admin route definitions - single source of truth for sidebar and tests
export const ADMIN_ROUTES = [
    { path: '/admin/events', sidebarLabel: 'Event Browser', pageHeading: 'Event Browser' },
    { path: '/admin/executions', sidebarLabel: 'Executions', pageHeading: 'Execution Management' },
    { path: '/admin/sagas', sidebarLabel: 'Sagas', pageHeading: 'Saga Management' },
    { path: '/admin/users', sidebarLabel: 'Users', pageHeading: 'User Management' },
    { path: '/admin/settings', sidebarLabel: 'Settings', pageHeading: 'System Settings' },
] as const;

export type AdminRoute = (typeof ADMIN_ROUTES)[number];
export type AdminPath = AdminRoute['path'];

// Common background colors for stats cards
export const STATS_BG_COLORS = {
    green: 'bg-green-50 dark:bg-green-900/20',
    red: 'bg-red-50 dark:bg-red-900/20',
    yellow: 'bg-yellow-50 dark:bg-yellow-900/20',
    blue: 'bg-blue-50 dark:bg-blue-900/20',
    purple: 'bg-purple-50 dark:bg-purple-900/20',
    orange: 'bg-orange-50 dark:bg-orange-900/20',
    neutral: 'bg-neutral-50 dark:bg-neutral-900/20'
} as const;

// Common text colors
export const STATS_TEXT_COLORS = {
    green: 'text-green-600 dark:text-green-400',
    red: 'text-red-600 dark:text-red-400',
    yellow: 'text-yellow-600 dark:text-yellow-400',
    blue: 'text-blue-600 dark:text-blue-400',
    purple: 'text-purple-600 dark:text-purple-400',
    orange: 'text-orange-600 dark:text-orange-400',
    neutral: 'text-neutral-600 dark:text-neutral-400'
} as const;

export type StatsBgColor = keyof typeof STATS_BG_COLORS;
export type StatsTextColor = keyof typeof STATS_TEXT_COLORS;
