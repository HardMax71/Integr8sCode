<script>
    // Simple SVG Icons (Keep as before)
    const telegramIcon = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>`;
    const githubIcon = `<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clip-rule="evenodd"/></svg>`;
</script>

<footer class="bg-bg-alt dark:bg-dark-bg-alt border-t border-border-default dark:border-dark-border-default mt-16">
    <div class="app-container py-12">

        <div class="grid grid-cols-1 md:grid-cols-12 gap-8 mb-8">

            <div class="md:col-span-5 lg:col-span-6">
                <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-2">
                    Integr8sCode
                </h2>
                <p class="text-base text-fg-muted dark:text-dark-fg-muted">
                    Run Python scripts online with ease and security, powered by Kubernetes.
                </p>
            </div>

            <div class="md:col-span-7 lg:col-span-6 grid grid-cols-2 gap-8">
                <div>
                    <h3 class="text-sm font-semibold text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-4">
                        Navigation
                    </h3>
                    <ul class="space-y-3 text-sm">
                        <li><a href="/"
                               class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150">Home</a>
                        </li>
                        <li><a href="/editor"
                               class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150">Code
                            Editor</a></li>
                    </ul>
                </div>
                <div>
                    <h3 class="text-sm font-semibold text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-4">
                        Tools & Info
                    </h3>
                    <ul class="space-y-3 text-sm">
                        <li><a href="http://localhost:9090" target="_blank" rel="noopener noreferrer"
                               class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150">Prometheus</a>
                        </li>
                        <li><a href="http://localhost:3000" target="_blank" rel="noopener noreferrer"
                               class="text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light transition-colors duration-150">Grafana</a>
                        </li>
                    </ul>
                </div>
            </div>
        </div>

        <div class="mt-8 pt-8 border-t border-border-default dark:border-dark-border-default flex flex-col sm:flex-row items-center justify-between gap-4">
            <p class="text-xs text-fg-muted dark:text-dark-fg-muted text-center sm:text-left">
                © {new Date().getFullYear()} Integr8sCode. Built by Max Azatian. All rights reserved.
            </p>
            <div class="flex space-x-5">
                {#if telegramIcon}
                    <a href="https://t.me/MaxAzatian" target="_blank" rel="noopener noreferrer" title="Telegram"
                       class="text-fg-muted dark:text-dark-fg-muted hover:text-primary dark:hover:text-primary-light transition-colors duration-200">
                        <span class="sr-only">Telegram</span>
                        {@html telegramIcon}
                    </a>
                {/if}
                {#if githubIcon}
                    <a href="https://github.com/HardMax71/Integr8sCode" target="_blank" rel="noopener noreferrer"
                       title="GitHub"
                       class="text-fg-muted dark:text-dark-fg-muted hover:text-primary dark:hover:text-primary-light transition-colors duration-200">
                        <span class="sr-only">GitHub</span>
                        {@html githubIcon}
                    </a>
                {/if}
            </div>
        </div>
    </div>
</footer>