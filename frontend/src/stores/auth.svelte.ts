import * as z from 'zod/mini';
import {
    getCurrentUserProfileApiV1AuthMeGetOptions,
    getCurrentUserProfileApiV1AuthMeGetQueryKey,
    zUserResponse,
    type LoginResponse,
    type UserResponse,
} from '#lib/api/index.ts';
import { queryClient } from '#lib/query-client.ts';
import { getLogger } from '@logtape/logtape';

const log = getLogger(['integr8scode', 'auth']);

// --8<-- [start:AuthState]
/** Only a signed-in session has a user and the CSRF token for writes */
export type Session = { status: 'signed-out' } | { status: 'signed-in'; user: UserResponse; csrfToken: string };

// sessionStorage keeps a signed-in session and when it was saved, so a reload signs in without a round trip
const zStoredSession = z.object({
    status: z.literal('signed-in'),
    user: zUserResponse,
    csrfToken: z.string(),
    timestamp: z.number(),
});
// --8<-- [end:AuthState]

const SIGNED_OUT: Session = { status: 'signed-out' };

/** The session this tab saved last and when; signed out, from the epoch, when there's none */
export function getPersistedAuthState(): { session: Session; timestamp: number } {
    if (typeof window === 'undefined') return { session: SIGNED_OUT, timestamp: 0 };
    try {
        const data = sessionStorage.getItem('authState');
        if (!data) return { session: SIGNED_OUT, timestamp: 0 };
        const stored = zStoredSession.safeParse(JSON.parse(data));
        if (stored.success) {
            const { timestamp, ...session } = stored.data;
            return { session, timestamp };
        }
        sessionStorage.removeItem('authState');
        return { session: SIGNED_OUT, timestamp: 0 };
    } catch {
        return { session: SIGNED_OUT, timestamp: 0 };
    }
}

function persistAuthState(session: Session) {
    if (typeof window === 'undefined') return;
    if (session.status === 'signed-out') {
        sessionStorage.removeItem('authState');
        return;
    }
    sessionStorage.setItem('authState', JSON.stringify({ ...session, timestamp: Date.now() }));
}

const persisted = getPersistedAuthState();

const VERIFY_STALE_MS = 30_000;
const STALE_AUTH_THRESHOLD = 5 * 60 * 1000;

class AuthStore {
    session = $state<Session>(persisted.session);

    #initialized = false;
    #initPromise: Promise<boolean> | null = null;

    clearAuth() {
        this.session = SIGNED_OUT;
        persistAuthState(SIGNED_OUT);
        // Nothing the previous user loaded may show to the next one
        queryClient.removeQueries();
    }

    async initialize(): Promise<boolean> {
        if (this.#initialized) return true;
        if (this.#initPromise) return this.#initPromise;

        this.#initPromise = this.#performInitialization();
        try {
            const result = await this.#initPromise;
            this.#initialized = true;
            return result;
        } catch (err) {
            this.#initialized = false;
            throw err;
        } finally {
            this.#initPromise = null;
        }
    }

    async waitForInit(): Promise<boolean> {
        if (this.#initialized) return true;
        if (this.#initPromise) return this.#initPromise;
        return this.initialize();
    }

    async #performInitialization(): Promise<boolean> {
        const { session, timestamp } = getPersistedAuthState();
        if (session.status === 'signed-out') return this.verifyAuth();

        this.session = session;
        // A 401 signs the session out; one the server couldn't be asked about stays while it's recent
        if (await this.verifyAuth(true, session.csrfToken, Date.now() - timestamp < STALE_AUTH_THRESHOLD)) return true;
        this.clearAuth();
        return false;
    }

    /** Takes over the session a successful login started and loads the user's profile before it resolves. */
    async startSession(login: LoginResponse): Promise<void> {
        await this.verifyAuth(true, login.csrf_token);
    }

    /**
     * Checks the session with the server. The profile query is cached for 30 seconds, so checks within that
     * window share one answer, and checks made at the same time share one request.
     *
     * OFFLINE-FIRST: on a network or server error it returns the last answer instead of signing the user out,
     * so a server-revoked session can look valid for up to 30 seconds; pass forceRefresh for sensitive actions.
     */
    async verifyAuth(
        forceRefresh = false,
        csrfToken = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)?.[1] ?? '',
        offlineAnswer = queryClient.getQueryData(getCurrentUserProfileApiV1AuthMeGetQueryKey()) !== undefined,
    ): Promise<boolean> {
        let user: UserResponse;
        try {
            user = await queryClient.query({
                ...getCurrentUserProfileApiV1AuthMeGetOptions(),
                staleTime: forceRefresh ? 0 : VERIFY_STALE_MS,
                retry: false,
            });
        } catch {
            if (queryClient.getQueryState(getCurrentUserProfileApiV1AuthMeGetQueryKey())?.error?.status === 401) {
                this.clearAuth();
                return false;
            }
            log.warning('Profile check failed, so the session stays {status}', { status: this.session.status });
            return offlineAnswer;
        }

        this.session = { status: 'signed-in', user, csrfToken };
        persistAuthState(this.session);
        return true;
    }
}

export const authStore = new AuthStore();
