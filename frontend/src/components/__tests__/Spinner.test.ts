import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Spinner from '#components/Spinner.svelte';

describe('Spinner', () => {
    it('is a status named Loading', () => {
        render(Spinner);
        expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument();
    });
});
