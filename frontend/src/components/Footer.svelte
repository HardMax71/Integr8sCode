<script>
    import { Icon, Send } from '@lucide/svelte';
    import { authStore } from '#stores/auth.svelte.ts';

    // Lucide 1.0 dropped its brand icons, so this is the GitHub mark it used to ship, drawn by its Icon.
    const github = {
        name: 'github',
        node: [
            [
                'path',
                {
                    d: 'M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4',
                },
            ],
            ['path', { d: 'M9 18c-4.51 2-5-2-7-2' }],
        ],
    };
</script>

<footer
    class="relative z-30 mt-8 pt-8 pb-6 bg-bg-alt dark:bg-dark-bg-alt border-t border-border-default dark:border-dark-border-default"
>
    <div class="app-container py-6">
        <div class="grid grid-cols-1 md:grid-cols-12 gap-8 mb-8">
            <div class="md:col-span-5 lg:col-span-6">
                <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-2">Integr8sCode</h2>
                <p class="text-base text-fg-muted dark:text-dark-fg-muted">
                    Run code online with ease and security, powered by Kubernetes.
                </p>
            </div>

            <div class="md:col-span-7 lg:col-span-6 grid grid-cols-2 gap-8">
                <div>
                    <h3
                        class="text-sm font-semibold text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-4"
                    >
                        Navigation
                    </h3>
                    <ul class="space-y-3 text-sm">
                        <li>
                            <a
                                href="/"
                                class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150"
                                >Home</a
                            >
                        </li>
                        <li>
                            <a
                                href="/editor"
                                class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150"
                                >Code Editor</a
                            >
                        </li>
                    </ul>
                </div>
                <div>
                    <h3
                        class="text-sm font-semibold text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-4"
                    >
                        Tools & Info
                    </h3>
                    <ul class="space-y-3 text-sm">
                        {#if authStore.userRole === 'admin'}
                            <li>
                                <a
                                    href="/grafana"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150"
                                    >Grafana</a
                                >
                            </li>
                        {/if}
                        <li>
                            <a
                                href="/privacy"
                                class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150"
                                >Privacy Policy</a
                            >
                        </li>
                    </ul>
                </div>
            </div>
        </div>

        <div
            class="mt-8 pt-8 border-t border-border-default dark:border-dark-border-default flex flex-col sm:flex-row items-center justify-between gap-4"
        >
            <p class="text-xs text-fg-muted dark:text-dark-fg-muted text-center sm:text-left">
                © {new Date().getFullYear()} Integr8sCode. Built by Max Azatian. All rights reserved.
            </p>
            <div class="flex space-x-5">
                <a
                    href="https://t.me/MaxAzatian"
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Telegram"
                    class="text-fg-muted dark:text-dark-fg-muted hover:text-primary dark:hover:text-primary-light transition-colors duration-200"
                >
                    <span class="sr-only">Telegram</span>
                    <Send size={20} />
                </a>
                <a
                    href="https://github.com/HardMax71/Integr8sCode"
                    target="_blank"
                    rel="noopener noreferrer"
                    title="GitHub"
                    class="text-fg-muted dark:text-dark-fg-muted hover:text-primary dark:hover:text-primary-light transition-colors duration-200"
                >
                    <span class="sr-only">GitHub</span>
                    <Icon icon={github} size={20} />
                </a>
            </div>
        </div>
    </div>
</footer>
