<script lang="ts">
    import {
        CirclePlay,
        CircleCheckBig,
        CircleX,
        Clock,
        FileInput,
        Zap,
        Check,
        X,
        CircleMinus,
        CircleQuestionMark,
    } from '@lucide/svelte';

    interface Props {
        eventType: string;
        size?: number;
    }

    let { eventType, size = 20 }: Props = $props();

    // Map event types to icon components
    const iconMap: Record<string, typeof CirclePlay> = {
        // Execution events
        'execution.requested': FileInput,
        execution_requested: FileInput,
        'execution.started': CirclePlay,
        execution_started: CirclePlay,
        'execution.completed': CircleCheckBig,
        execution_completed: CircleCheckBig,
        'execution.failed': CircleX,
        execution_failed: CircleX,
        'execution.timeout': Clock,
        execution_timeout: Clock,
        // Pod events
        'pod.created': Zap,
        pod_created: Zap,
        'pod.running': Zap,
        pod_running: Zap,
        'pod.succeeded': Check,
        pod_succeeded: Check,
        'pod.failed': X,
        pod_failed: X,
        'pod.terminated': CircleMinus,
        pod_terminated: CircleMinus,
    };

    const Icon = $derived(iconMap[eventType] || CircleQuestionMark);
</script>

<Icon {size} />
