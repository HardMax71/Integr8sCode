/**
 * Rate limit configurations and utilities for user management
 */
import type { EndpointGroup } from '#lib/api/index.ts';

// Group colors for rate limit endpoint groups
const GROUP_COLORS: Record<EndpointGroup, string> = {
    execution: 'bg-purple-soft text-purple',
    admin: 'bg-danger-soft text-danger',
    sse: 'bg-warning-soft text-warning',
    websocket: 'bg-success-soft text-success',
    auth: 'bg-info-soft text-info',
    api: 'bg-muted text-fg',
    public: 'bg-indigo-soft text-indigo',
};

export function getGroupColor(group: EndpointGroup): string {
    return GROUP_COLORS[group];
}
