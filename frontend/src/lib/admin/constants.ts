// Admin route definitions - single source of truth for sidebar and tests
export const ADMIN_ROUTES = [
    { path: '/admin/events', sidebarLabel: 'Event Browser', pageHeading: 'Event Browser' },
    { path: '/admin/executions', sidebarLabel: 'Executions', pageHeading: 'Execution Management' },
    { path: '/admin/users', sidebarLabel: 'Users', pageHeading: 'User Management' },
    { path: '/admin/settings', sidebarLabel: 'Settings', pageHeading: 'System Settings' },
] as const;

export type AdminRoute = (typeof ADMIN_ROUTES)[number];
export type AdminPath = AdminRoute['path'];
