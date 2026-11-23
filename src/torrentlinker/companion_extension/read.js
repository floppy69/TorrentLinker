// Runs in the c411 tab's isolated world. Session credentials never leave it.
// Only the fixed catalogue pages below are read (adult content the API key cannot
// see); never turn arbitrary URLs into browser requests. executeScript serializes
// only this function, so it must not use outer names.
export async function readPages(commands) {
  const account = commands[0]?.accountId;
  const allowed = [
    /^\/api\/categories$/,
    /^\/api\/categories\/8\/filter-options$/,
    /^\/api\/torrents\?(?=(?:[A-Za-z0-9_=%.,+~-]+&)*category=8(?:&|$))[A-Za-z0-9_=&%.,+~-]{1,1500}$/,
  ];
  const get = (path) => fetch(path, {
    credentials: "same-origin", redirect: "error", cache: "no-store",
    signal: AbortSignal.timeout(30000),
  });
  const fail = (command, status, extra = {}) => ({
    id: command.id, accountId: command.accountId, status, ...extra,
  });
  const results = [];
  try {
    if (location.origin !== "https://c411.org" ||
        commands.some((c) => c.accountId !== account || !allowed.some((r) => r.test(c.path))))
      return commands.map((c) => fail(c, 0, { reason: "origin" }));
    const same = async () => {
      const response = await get("/api/user/profile");
      return response.ok ? String((await response.json()).id) === account : false;
    };
    if (!(await same())) return commands.map((c) => fail(c, 403, { reason: "account" }));
    for (const command of commands) {
      const response = await get(command.path);
      if (!response.ok) {
        const value = response.headers.get("retry-after") || "";
        const seconds = /^\d+$/.test(value) ? Number(value) : Math.ceil((Date.parse(value) - Date.now()) / 1000);
        results.push(fail(command, response.status, response.status === 429
          ? { retryAfter: Number.isFinite(seconds) ? Math.max(60, seconds) : 60 } : {}));
        if (response.status !== 404) break;
        continue;
      }
      const text = await response.text();
      results.push(text.length > 4 * 1024 * 1024
        ? fail(command, 0, { reason: "size" })
        : { id: command.id, accountId: command.accountId, status: 200, data: text });
    }
  } catch (error) {
    // Never send exception messages, response bodies, login tokens or URLs.
    results.push(fail(commands[results.length], 0, { reason: error?.name === "TimeoutError" ? "timeout" : "network" }));
  }
  while (results.length < commands.length) results.push(fail(commands[results.length], 0, { reason: "stopped" }));
  return results;
}
