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
    green: 'bg-success-soft',
    red: 'bg-danger-soft',
    yellow: 'bg-warning-soft',
    blue: 'bg-info-soft',
    purple: 'bg-purple-soft',
    orange: 'bg-orange-soft',
    neutral: 'bg-muted',
} as const;

// Common text colors
export const STATS_TEXT_COLORS = {
    green: 'text-success',
    red: 'text-danger',
    yellow: 'text-warning',
    blue: 'text-info',
    purple: 'text-purple',
    orange: 'text-orange',
    neutral: 'text-fg-muted',
} as const;

export type StatsBgColor = keyof typeof STATS_BG_COLORS;
export type StatsTextColor = keyof typeof STATS_TEXT_COLORS;
