import type { UserResponse } from '#lib/api/index.ts';

/** Stands in for $app/state's page, which needs a running app; a test sets the url and the user it needs */
export const page = $state<{ url: URL; data: { user: UserResponse | null } }>({
    url: new URL('https://localhost/'),
    data: { user: null },
});
