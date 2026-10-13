import type { Component } from 'svelte';
import { CircleAlert, CircleCheck, Info, TriangleAlert } from '@lucide/svelte';
import type { NotificationSeverity } from '#lib/api/index.ts';

export const SEVERITY_COLORS: Record<NotificationSeverity, string> = {
    low: 'text-fg-muted',
    medium: 'text-info',
    high: 'text-orange',
    urgent: 'text-danger',
};

/** Tags are free strings in the API; these are the ones the backend's notifications carry */
export function notificationIcon(tags: string[]): Component {
    const set = new Set(tags);
    if (set.has('failed') || set.has('error') || set.has('security')) return CircleAlert;
    if (set.has('timeout') || set.has('warning')) return TriangleAlert;
    if (set.has('completed') || set.has('success')) return CircleCheck;
    return Info;
}
