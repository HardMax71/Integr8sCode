import { randomUUID } from 'node:crypto';
import {
    test as base,
    expect,
    type APIRequest,
    type APIRequestContext,
    type BrowserContextOptions,
    type Dialog,
    type Page,
    type TestInfo,
} from '@playwright/test';
import { attachCoverageReport } from 'monocart-reporter';
import type {
    ExecutionRequest,
    ExecutionResponse,
    LoginResponse,
    UserCreate,
    UserResponse,
} from '#lib/api/types.gen.ts';

/** The admin that seed_users.py creates, with the password it reads from the same variable */
const ADMIN = { username: 'admin', password: process.env.ADMIN_USER_PASSWORD ?? 'admin123' };

export interface Account {
    user_id: string;
    username: string;
    email: string;
    password: string;
}

/** What a browser context or an API client needs to act as a signed-in user */
interface Session {
    storageState: Exclude<BrowserContextOptions['storageState'], string | undefined>;
    csrfToken: string;
}

interface WorkerFixtures {
    account: Account;
    userSession: Session;
    adminSession: Session;
}

interface TestFixtures {
    userPage: Page;
    adminPage: Page;
    api: APIRequestContext;
    execution: ExecutionResponse;
}

/** Registers a new account, so no two workers ever share a user's settings, scripts or notifications */
async function register(request: APIRequest, baseURL: string | undefined): Promise<Account> {
    await using api = await request.newContext({ baseURL, ignoreHTTPSErrors: true });
    const username = `e2e-${randomUUID()}`;
    const body: UserCreate = { username, email: `${username}@example.com`, password: randomUUID() };
    const response = await api.post('/api/v1/auth/register', { data: body });
    await expect(response).toBeOK();
    const user = (await response.json()) as UserResponse;
    return { user_id: user.user_id, username, email: body.email, password: body.password };
}

/** Logs in through the API and keeps the cookies it sets */
async function logIn(
    request: APIRequest,
    baseURL: string | undefined,
    credentials: { username: string; password: string },
): Promise<Session> {
    await using api = await request.newContext({ baseURL, ignoreHTTPSErrors: true });
    const response = await api.post('/api/v1/auth/login', { form: credentials });
    await expect(response).toBeOK();
    const { csrf_token } = (await response.json()) as LoginResponse;
    return { storageState: await api.storageState(), csrfToken: csrf_token };
}

/** Hands the page to the test and attaches the JS coverage it collected for the monocart reporter */
async function useWithCoverage(page: Page, use: (page: Page) => Promise<void>, testInfo: TestInfo): Promise<void> {
    await page.coverage.startJSCoverage({ resetOnNavigation: false });
    await use(page);
    await attachCoverageReport(await page.coverage.stopJSCoverage(), testInfo);
}

/** A route handler that never answers, so a test can look at the UI while the request is pending */
export function holdRequest(): void {}

/** Accepts the next confirm() the page shows */
export function acceptDialog(dialog: Dialog): Promise<void> {
    return dialog.accept();
}

export const test = base.extend<TestFixtures, WorkerFixtures>({
    account: [
        async ({ playwright }, use, { project }) => use(await register(playwright.request, project.use.baseURL)),
        { scope: 'worker' },
    ],
    userSession: [
        async ({ playwright, account }, use, { project }) =>
            use(await logIn(playwright.request, project.use.baseURL, account)),
        { scope: 'worker' },
    ],
    adminSession: [
        async ({ playwright }, use, { project }) => use(await logIn(playwright.request, project.use.baseURL, ADMIN)),
        { scope: 'worker' },
    ],

    // Every page is a fresh context: a guest's `page`, or one that starts with the worker's session cookies
    page: async ({ page }, use, testInfo) => useWithCoverage(page, use, testInfo),
    userPage: async ({ browser, userSession }, use, testInfo) => {
        await using context = await browser.newContext({ storageState: userSession.storageState });
        await useWithCoverage(await context.newPage(), use, testInfo);
    },
    adminPage: async ({ browser, adminSession }, use, testInfo) => {
        await using context = await browser.newContext({ storageState: adminSession.storageState });
        await useWithCoverage(await context.newPage(), use, testInfo);
    },

    api: async ({ playwright, userSession }, use) => {
        await using api = await playwright.request.newContext({
            storageState: userSession.storageState,
            extraHTTPHeaders: { 'X-CSRF-Token': userSession.csrfToken },
        });
        await use(api);
    },
    execution: async ({ api }, use) => {
        const body: ExecutionRequest = { script: `print("${randomUUID()}")` };
        const response = await api.post('/api/v1/execute', { data: body });
        await expect(response).toBeOK();
        await use((await response.json()) as ExecutionResponse);
    },
});

export { expect };
