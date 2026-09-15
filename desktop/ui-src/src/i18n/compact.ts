// Build-time i18n key compaction (used only by vite.config.ts, never bundled).
//
// Keys such as "obs.hostFingerprint" are great in source but cost bytes three
// times over in the output (en object, uz/ru objects, every t() call site). At
// build time every exact key literal is rewritten to a short id in the same
// deterministic order as en.ts, so lookups stay identical. Keys are only ever
// referenced as whole string literals (enforced by tests/unit/i18n.test.ts).

const KEY_LINE = /^\s*"([a-z]+\.[A-Za-z0-9.]+)":/gm;
const LITERAL = /(["'])([a-z]+\.[A-Za-z0-9.]+)\1/g;

/** Ordered keys of en.ts (one `"key": "value",` per line). */
export function extractKeys(enSource: string): string[] {
  return [...enSource.matchAll(KEY_LINE)].map((m) => m[1]);
}

/** Short, never integer-like ids: a..z, a1..z1, a2.. */
export function shortId(index: number): string {
  const letter = String.fromCharCode(97 + (index % 26));
  const round = Math.floor(index / 26);
  return round ? letter + round.toString(36) : letter;
}

export function buildKeyMap(enSource: string): Map<string, string> {
  return new Map(extractKeys(enSource).map((key, i) => [key, shortId(i)]));
}

/** Replace exact i18n key string literals; everything else is untouched. */
export function compactKeys(code: string, map: ReadonlyMap<string, string>): string {
  return code.replace(LITERAL, (match, quote: string, key: string) => {
    const id = map.get(key);
    return id === undefined ? match : quote + id + quote;
  });
}
