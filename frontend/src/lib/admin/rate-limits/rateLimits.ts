/**
 * Rate limit configurations and utilities for user management
 */
import type { RateLimitRuleResponse, EndpointGroup } from '$lib/api';

// Group colors for rate limit endpoint groups
export const GROUP_COLORS: Record<EndpointGroup, string> = {
    execution: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
    admin: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    sse: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    websocket: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    auth: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    api: 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-200',
    public: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200'
};

export function getGroupColor(group: EndpointGroup): string {
    return GROUP_COLORS[group];
}

// Patterns to detect endpoint groups from URL patterns
export const ENDPOINT_GROUP_PATTERNS: Array<{ pattern: RegExp; group: EndpointGroup }> = [
    { pattern: /\/execute/i, group: 'execution' },
    { pattern: /\/admin\//i, group: 'admin' },
    { pattern: /\/events\//i, group: 'sse' },
    { pattern: /\/ws/i, group: 'websocket' },
    { pattern: /\/auth\//i, group: 'auth' },
    { pattern: /\/health/i, group: 'public' }
];

export function detectGroupFromEndpoint(endpoint: string): EndpointGroup {
    // Strip regex anchors: leading ^, trailing $, and .* wildcards
    const cleanEndpoint = endpoint.replace(/^\^/, '').replace(/\$$/, '').replace(/\.\*/g, '');
    for (const { pattern, group } of ENDPOINT_GROUP_PATTERNS) {
        if (pattern.test(cleanEndpoint)) return group;
    }
    return 'api';
}

// Create a new empty rate limit rule
export function createEmptyRule(): RateLimitRuleResponse {
    return {
        endpoint_pattern: '',
        group: 'api',
        requests: 60,
        window_seconds: 60,
        burst_multiplier: 1.5,
        algorithm: 'sliding_window',
        priority: 0,
        enabled: true
    };
}
