/**
 * Rate limit configurations and utilities for user management
 */
import type { EndpointGroup } from '#lib/api/index.ts';

// Group colors for rate limit endpoint groups
const GROUP_COLORS: Record<EndpointGroup, string> = {
    execution: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
    admin: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    sse: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    websocket: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    auth: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    api: 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-200',
    public: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
};

export function getGroupColor(group: EndpointGroup): string {
    return GROUP_COLORS[group];
}
