import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { UserRole } from '#lib/api/index.ts';

import Footer from '#components/Footer.svelte';
import { page } from '#test/page.svelte.ts';

describe('Footer', () => {
    describe('branding', () => {
        it('displays brand name', () => {
            render(Footer);

            expect(screen.getByRole('heading', { name: /Integr8sCode/i })).toBeInTheDocument();
        });

        it('displays tagline', () => {
            render(Footer);

            expect(screen.getByText(/Run code online with ease and security/i)).toBeInTheDocument();
        });
    });

    describe('navigation links', () => {
        it('displays Navigation section', () => {
            render(Footer);

            expect(screen.getByRole('heading', { name: /Navigation/i })).toBeInTheDocument();
        });

        it('has Home link', () => {
            render(Footer);

            const homeLink = screen.getByRole('link', { name: /^Home$/i });
            expect(homeLink).toBeInTheDocument();
            expect(homeLink.getAttribute('href')).toBe('/');
        });

        it('has Code Editor link', () => {
            render(Footer);

            const editorLink = screen.getByRole('link', { name: /Code Editor/i });
            expect(editorLink).toBeInTheDocument();
            expect(editorLink.getAttribute('href')).toBe('/editor');
        });
    });

    describe('tools and info section', () => {
        it('displays Tools & Info section', () => {
            render(Footer);

            expect(screen.getByRole('heading', { name: /Tools & Info/i })).toBeInTheDocument();
        });

        it('shows admins a Grafana link to the nginx redirect', () => {
            page.data.user = { ...fakeUserResponse(), role: UserRole.ADMIN };
            render(Footer);

            const grafanaLink = screen.getByRole('link', { name: /Grafana/i });
            expect(grafanaLink.getAttribute('href')).toBe('/grafana');
            expect(grafanaLink.getAttribute('target')).toBe('_blank');
            expect(grafanaLink.getAttribute('rel')).toContain('noopener');
        });

        it.each([
            ['signed out', null],
            ['signed in as a regular user', UserRole.USER],
        ])('hides the Grafana link when %s', (_label, role) => {
            page.data.user = role ? { ...fakeUserResponse(), role } : null;
            render(Footer);

            expect(screen.queryByRole('link', { name: /Grafana/i })).not.toBeInTheDocument();
        });

        it('has Privacy Policy link', () => {
            render(Footer);

            const privacyLink = screen.getByRole('link', { name: /Privacy Policy/i });
            expect(privacyLink).toBeInTheDocument();
            expect(privacyLink.getAttribute('href')).toBe('/privacy');
        });
    });

    describe('social links', () => {
        it.each([
            ['Telegram', 'https://t.me/MaxAzatian'],
            ['GitHub', 'https://github.com/HardMax71/Integr8sCode'],
        ])('links to %s in a new tab without passing the opener or referrer', (name, href) => {
            render(Footer);

            const link = screen.getByRole('link', { name });
            expect(link).toHaveAttribute('href', href);
            expect(link).toHaveAttribute('target', '_blank');
            expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        });

        it('has screen reader text for social icons', () => {
            render(Footer);

            expect(screen.getByText('Telegram', { selector: '.sr-only' })).toBeInTheDocument();
            expect(screen.getByText('GitHub', { selector: '.sr-only' })).toBeInTheDocument();
        });
    });

    describe('copyright', () => {
        it('displays current year', () => {
            vi.setSystemTime(new Date(2025, 5, 15));
            render(Footer);

            expect(screen.getByText(/© 2025 Integr8sCode/)).toBeInTheDocument();
        });

        it('credits the author', () => {
            render(Footer);

            expect(screen.getByText(/Max Azatian/)).toBeInTheDocument();
        });

        it('includes rights reserved text', () => {
            render(Footer);

            expect(screen.getByText(/All rights reserved/)).toBeInTheDocument();
        });
    });

    describe('accessibility', () => {
        it('uses semantic footer element', () => {
            const { container } = render(Footer);

            expect(container.querySelector('footer')).toBeInTheDocument();
        });

        it('has proper heading hierarchy', () => {
            render(Footer);

            const h2 = screen.getByRole('heading', { level: 2 });
            expect(h2).toHaveTextContent('Integr8sCode');

            const h3s = screen.getAllByRole('heading', { level: 3 });
            expect(h3s.length).toBeGreaterThanOrEqual(2);
        });
    });
});
