import type { UserResponse } from '#lib/api/index.ts';

declare global {
    namespace App {
        interface PageData {
            /** Who is signed in, from the root layout's load */
            user: UserResponse | null;
        }
    }
}

export {};
