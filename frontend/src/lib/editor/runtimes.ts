export function newestVersion(versions: readonly string[]): string | undefined {
    return [...versions].sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))[0];
}
