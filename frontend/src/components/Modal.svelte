<script lang="ts">
    import type { Snippet } from 'svelte';
    import { Dialog } from 'bits-ui';
    import { X } from '@lucide/svelte';

    interface Props {
        open: boolean;
        title: string;
        onClose: () => void;
        size?: 'sm' | 'md' | 'lg' | 'xl';
        children: Snippet;
        footer?: Snippet;
    }

    let { open, title, onClose, size = 'lg', children, footer }: Props = $props();

    const sizeClasses = {
        sm: 'max-w-md',
        md: 'max-w-2xl',
        lg: 'max-w-4xl',
        xl: 'max-w-6xl',
    };
</script>

<Dialog.Root
    {open}
    onOpenChange={(next) => {
        if (!next) onClose();
    }}
>
    <Dialog.Portal>
        <Dialog.Overlay
            class="fixed inset-0 z-50 bg-backdrop data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0"
        />
        <Dialog.Content
            class="fixed left-1/2 top-1/2 z-50 flex max-h-[95vh] sm:max-h-[90vh] w-[calc(100%-1rem)] sm:w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg bg-surface shadow-xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 {sizeClasses[
                size
            ]}"
        >
            <div class="flex shrink-0 items-center justify-between border-b p-4 sm:p-6">
                <Dialog.Title class="text-lg sm:text-xl font-semibold">
                    {title}
                </Dialog.Title>
                <Dialog.Close aria-label="Close dialog" class="rounded-md text-fg-muted hover:text-fg">
                    <X size={24} />
                </Dialog.Close>
            </div>
            <div class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
                {@render children()}
            </div>
            {#if footer}
                <div class="flex shrink-0 justify-end gap-3 border-t p-4 sm:p-6">
                    {@render footer()}
                </div>
            {/if}
        </Dialog.Content>
    </Dialog.Portal>
</Dialog.Root>
