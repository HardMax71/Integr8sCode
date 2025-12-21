<script>
    import { onMount } from 'svelte';
    
    // PRIVACY POLICY CONFIGURATION - Update these values
    let lastUpdated = "August 30, 2025";
    let effectiveDate = "August 30, 2025";
    
    // Data Controller Information
    let operatorName = "Max Azatian";
    let operatorEmail = "max.azatian@gmail.com";
    let operatorLocation = "Germany";
    
    onMount(() => {
        window.scrollTo(0, 0);
    });
</script>

<svelte:head>
    <title>Privacy Policy | Integr8sCode</title>
</svelte:head>

<div class="container mx-auto px-4 py-8 max-w-4xl">
    <div class="bg-bg-white dark:bg-dark-bg-alt rounded-lg shadow-xs border border-border-default dark:border-dark-border-default p-8">
        <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default mb-2">Privacy Policy</h1>
        <p class="text-sm text-fg-muted dark:text-dark-fg-muted mb-8">
            Last updated: {lastUpdated}
        </p>

        <div class="prose-page prose prose-lg dark:prose-invert max-w-none space-y-6 text-fg-default dark:text-dark-fg-default">
            
            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Hi there!</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    I'm {operatorName}, and I built Integr8sCode as a personal project. This is an online code execution platform that lets you run Python scripts in isolated environments. Since I'm handling your data, I want to be transparent about what information I collect and how I use it.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    This privacy policy complies with GDPR and other data protection laws. If you have any questions, just drop me an email at <a href="mailto:{operatorEmail}" class="text-primary dark:text-primary-light hover:underline">{operatorEmail}</a>.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Who's responsible for your data?</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    That would be me:
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    {operatorName}<br>
                    <a href="mailto:{operatorEmail}" class="text-primary dark:text-primary-light hover:underline">{operatorEmail}</a><br>
                    Based in {operatorLocation}
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    Since this is a personal project, I handle all privacy matters myself. No corporate bureaucracy here – just email me directly if you have concerns.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">What information do I collect?</h2>
                
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    When you create an account, I store your username, email address, and a securely hashed version of your password. I also keep track of when you created your account and when it was last updated.
                </p>

                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    When you run code, I temporarily store the script you submitted, which programming language you chose, and the output it generates. I also track basic metrics like how long your code took to run and how much memory it used – this helps prevent abuse and shows you performance information.
                </p>

                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    For security purposes, server logs capture your IP address and browser information. This helps me detect and prevent attacks, enforce rate limits, and keep the service running smoothly. These logs are automatically deleted after 7 days.
                </p>

                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    I don't use any analytics services like Google Analytics, and I don't track you around the web. The only cookies I use are essential ones for keeping you logged in and remembering your theme preference.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Why do I need this information?</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    Pretty straightforward – I need your email and password to create your account and let you log in. The code execution data is necessary to, well, execute your code and show you the results. The security logs help me keep the platform safe from abuse and attacks.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    Under GDPR terms, I process your data based on our contract (providing you the service), legitimate interests (security and preventing abuse), and legal obligations (when required by law).
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">How long do I keep your data?</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    Your account information stays as long as you have an account, plus 30 days after deletion (in case you change your mind or there are legal issues). Code execution data is kept for 90 days to help with debugging and support. Security logs are automatically purged after 7 days. Performance metrics are aggregated and anonymized after 30 days.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Who else sees your data?</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    Almost nobody. The server hosting provider has physical access to the infrastructure, but they can't access your actual data. I might have to share information if legally required (court order, etc.), but that hasn't happened and hopefully never will.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    I don't sell your data. I don't share it with advertisers. I don't even have advertisers. This is a personal project, not a data harvesting operation.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">How do I protect your data?</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    I use industry-standard security measures: HTTPS encryption for all connections, bcrypt for password hashing, isolated Kubernetes pods for code execution, and regular security updates. Your code runs in a sandboxed environment that's destroyed after execution.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    That said, no system is 100% secure. I do my best to protect your data, but I can't guarantee absolute security – nobody can, really.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Your rights (GDPR stuff)</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    Under GDPR, you have several rights regarding your data. You can request a copy of your data, ask me to correct mistakes, delete your account and data, restrict how I process your data, export your data in a portable format, object to certain processing, or withdraw consent at any time.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    To exercise any of these rights, just email me at <a href="mailto:{operatorEmail}?subject=GDPR%20Request" class="text-primary dark:text-primary-light hover:underline">{operatorEmail}</a>. I'll handle your request personally and respond within the GDPR-required timeframe.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Where's your data stored?</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    Everything is hosted on servers in {operatorLocation}, which is in the EU. Your data doesn't leave the EU, so it's protected by GDPR. If you're accessing this from outside the EU, your data gets transferred here for processing.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">About cookies</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    I only use essential cookies – the ones needed to keep you logged in and remember if you prefer dark mode. No tracking cookies, no advertising cookies, no third-party cookies. Just the bare minimum to make the site work.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Kids and this service</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    This service isn't for anyone under 16. If you're a parent and think your child has created an account, please <a href="mailto:{operatorEmail}?subject=Minor%20Account%20Concern" class="text-primary dark:text-primary-light hover:underline">let me know</a> and I'll delete it.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">The tech stack</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    I use various open-source tools to run this service, all self-hosted on my own infrastructure. This includes MongoDB for data storage, Kubernetes for code execution, Kafka for event processing, and several monitoring tools. These all run locally – your data never goes to the companies that make these tools.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    Everything runs on my server. No external services get your data. No telemetry gets sent to third parties. It's all self-contained.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Changes to this policy</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    If I need to update this privacy policy, I'll post the new version here and update the date at the top. I recommend checking back occasionally, especially if privacy is important to you.
                </p>
            </section>

            <section>
                <h2 class="text-2xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Get in touch</h2>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed">
                    Questions? Concerns? Just want to chat about privacy? Email me at <a href="mailto:{operatorEmail}?subject=Privacy%20Question" class="text-primary dark:text-primary-light hover:underline">{operatorEmail}</a>. I usually respond within 72 hours.
                </p>
                <p class="text-fg-default dark:text-dark-fg-default leading-relaxed mt-3">
                    If you're in the EU and I can't resolve your privacy concern, you can also contact your local data protection authority. But I'd appreciate it if you'd <a href="mailto:{operatorEmail}?subject=Privacy%20Concern" class="text-primary dark:text-primary-light hover:underline">talk to me first</a> – I'm pretty reasonable and want to help.
                </p>
            </section>

            <section class="mt-8 pt-8 border-t border-border-default dark:border-dark-border-default">
                <p class="text-sm text-fg-muted dark:text-dark-fg-muted">
                    This privacy policy was written in plain English because legal jargon helps nobody. If something isn't clear, just ask. Thanks for trusting me with your data – I take that responsibility seriously.
                </p>
            </section>
        </div>
    </div>
</div>