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
    import { EventType } from '#lib/api/index.ts';

    interface Props {
        eventType: EventType;
        size?: number;
    }

    let { eventType, size = 20 }: Props = $props();

    const iconMap: Partial<Record<EventType, typeof CirclePlay>> = {
        [EventType.EXECUTION_REQUESTED]: FileInput,
        [EventType.EXECUTION_STARTED]: CirclePlay,
        [EventType.EXECUTION_COMPLETED]: CircleCheckBig,
        [EventType.EXECUTION_FAILED]: CircleX,
        [EventType.EXECUTION_TIMEOUT]: Clock,
        [EventType.POD_CREATED]: Zap,
        [EventType.POD_RUNNING]: Zap,
        [EventType.POD_SUCCEEDED]: Check,
        [EventType.POD_FAILED]: X,
        [EventType.POD_TERMINATED]: CircleMinus,
    };

    const Icon = $derived(iconMap[eventType] ?? CircleQuestionMark);
</script>

<Icon {size} />
