<script lang="ts">
  import {
    PlayCircle,
    CheckCircle,
    XCircle,
    Clock,
    FileInput,
    Zap,
    Check,
    X,
    MinusCircle,
    HelpCircle,
  } from '@lucide/svelte';

  interface Props {
    eventType: string;
    size?: number;
  }

  let { eventType, size = 20 }: Props = $props();

  // Map event types to icon components
  const iconMap: Record<string, typeof PlayCircle> = {
    // Execution events
    'execution.requested': FileInput,
    'execution_requested': FileInput,
    'execution.started': PlayCircle,
    'execution_started': PlayCircle,
    'execution.completed': CheckCircle,
    'execution_completed': CheckCircle,
    'execution.failed': XCircle,
    'execution_failed': XCircle,
    'execution.timeout': Clock,
    'execution_timeout': Clock,
    // Pod events
    'pod.created': Zap,
    'pod_created': Zap,
    'pod.running': Zap,
    'pod_running': Zap,
    'pod.succeeded': Check,
    'pod_succeeded': Check,
    'pod.failed': X,
    'pod_failed': X,
    'pod.terminated': MinusCircle,
    'pod_terminated': MinusCircle,
  };

  const icon = $derived(iconMap[eventType] || HelpCircle);
</script>

<svelte:component this={icon} {size} />
