import type { EndpointGroup } from '#lib/api/index.ts';

export const GROUP_COLORS: Record<EndpointGroup, string> = {
    execution: 'bg-purple-soft text-purple',
    admin: 'bg-danger-soft text-danger',
    sse: 'bg-warning-soft text-warning',
    websocket: 'bg-success-soft text-success',
    auth: 'bg-info-soft text-info',
    api: 'bg-muted',
    public: 'bg-indigo-soft text-indigo',
};
