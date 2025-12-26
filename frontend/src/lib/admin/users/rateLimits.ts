/**
 * Rate limit configurations and utilities for user management
 */
import type { RateLimitRule, EndpointGroup } from '$lib/api';

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
    const cleanEndpoint = endpoint.replaceAll(/^\^?/g, '').replaceAll(/\$?/g, '').replaceAll(/\.\*/g, '');
    for (const { pattern, group } of ENDPOINT_GROUP_PATTERNS) {
        if (pattern.test(cleanEndpoint)) return group;
    }
    return 'api';
}

// Default rate limit rules
export interface DefaultRateLimitRule extends Omit<RateLimitRule, 'enabled' | 'burst_multiplier'> {
    effective_requests?: number;
}

export function getDefaultRules(): DefaultRateLimitRule[] {
    return [
        { endpoint_pattern: '^/api/v1/execute', group: 'execution', requests: 10, window_seconds: 60, algorithm: 'sliding_window', priority: 10 },
        { endpoint_pattern: '^/api/v1/admin/.*', group: 'admin', requests: 100, window_seconds: 60, algorithm: 'sliding_window', priority: 5 },
        { endpoint_pattern: '^/api/v1/events/.*', group: 'sse', requests: 5, window_seconds: 60, algorithm: 'sliding_window', priority: 8 },
        { endpoint_pattern: '^/api/v1/ws', group: 'websocket', requests: 5, window_seconds: 60, algorithm: 'sliding_window', priority: 8 },
        { endpoint_pattern: '^/api/v1/auth/.*', group: 'auth', requests: 20, window_seconds: 60, algorithm: 'sliding_window', priority: 7 },
        { endpoint_pattern: '^/api/v1/.*', group: 'api', requests: 60, window_seconds: 60, algorithm: 'sliding_window', priority: 1 }
    ];
}

export function getDefaultRulesWithMultiplier(multiplier: number = 1): DefaultRateLimitRule[] {
    const rules = getDefaultRules();
    // Only positive multipliers are valid; 0 and negative values fall back to 1
    const effectiveMultiplier = multiplier > 0 ? multiplier : 1;
    return rules.map(rule => ({
        ...rule,
        effective_requests: Math.floor(rule.requests * effectiveMultiplier)
    }));
}

// Create a new empty rate limit rule
export function createEmptyRule(): RateLimitRule {
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
