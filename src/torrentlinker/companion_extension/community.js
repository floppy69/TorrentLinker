// Serialized into the c411 isolated world. No session or CSRF token leaves the tab.
// Both collection and execution use fixed routes; the owner approves a saved draft
// by queuing it in TorrentLinker. Never turn arbitrary URLs into browser requests.
export async function communityInTab(request) {
  let sending = false;
  const command = request.command;
  const fail = (outcome, reason, extra = {}) => ({outcome, reason, ...extra});
  const normal = (s) => String(s).replace(/<[^>]*>/g," ").normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu," ").trim();
  const get = async (path) => {
    const response = await fetch(path, {credentials: "same-origin", redirect: "error",
      cache: "no-store", signal: AbortSignal.timeout(15000)});
    if (!response.ok) {
      const error = new Error("read"); error.status = response.status;
      const retry = response.headers.get("retry-after");
      error.retryAfter = /^\d+$/.test(retry || "") ? Number(retry) : Math.max(60, Math.ceil((Date.parse(retry) - Date.now()) / 1000));
      throw error;
    }
    const body = await response.json();
    if (!body || body.success === false || body.error) throw new Error("schema");
    return body;
  };
  const channelsFor = async (profile) => {
    const body = await get("/api/messages/channels?space=public");
    const rows = Array.isArray(body.data) ? body.data : body.data?.public;
    if (!Array.isArray(rows)) throw new Error("schema");
    const slug = String(profile.class?.effectiveSlug || profile.class?.slug || "").replace(/-/g, "_");
    return rows.filter(c => c.canWrite === true && !c.isArchived &&
      (c.isDefault === true && !c.classSlug || c.classSlug && c.classSlug.replace(/-/g, "_") === slug))
      .map(c => ({id: c.id, name: String(c.name).slice(0, 160), kind: c.classSlug ? "class" : "general"}));
  };
  const rules = async () => {
    const body = await get("/api/ic/actions-catalog");
    const result = {};
    for (const [kind, type] of Object.entries({comment: "comment_post", vote: "trust_vote", chat: "shout_message"})) {
      const r = body.entries?.find(e => e.actionType === type && e.audience === "all");
      if (!r || !Number.isSafeInteger(r.today) || !Number.isSafeInteger(r.dailyLimit) ||
          !Number.isSafeInteger(r.cooldownSec)) throw new Error("schema");
      result[kind] = {today: r.today, limit: Math.min(5, r.dailyLimit),
        cooldown: r.cooldownSec, locked: !!r.lock};
    }
    return result;
  };
  try {
    if (location.origin !== "https://c411.org") return fail("refused", "account");
    const profile = await get("/api/user/profile");
    if (String(profile.id) !== request.accountId) return fail("refused", "account");
    const limits = await rules();
    if (!command) {
      const page = request.page;
      if (!Number.isSafeInteger(page) || page < 1 || page > 100000) throw new Error("schema");
      const seeds = request.seeds === false ? {data: []} : await get(`/api/profile/active-seeds?page=${page}&perPage=25`);
      if (!Array.isArray(seeds.data)) throw new Error("schema");
      const channels = await channelsFor(profile);
      if (String((await get("/api/user/profile")).id) !== request.accountId) return fail("refused", "account");
      const total = seeds.meta?.total;
      const pages = seeds.meta?.totalPages;
      const has_more = request.seeds !== false && (Number.isInteger(pages) ? page < pages :
        Number.isInteger(total) ? page * 25 < total : seeds.data.length >= 25);
      return {snapshot: {rules: limits, channels, page, has_more, seeds: request.seeds !== false, scan: request.scan || "", candidates: seeds.data.slice(0, 50).map(s => ({
        hash: s.infoHash, title: String(s.name).slice(0, 300),
      }))}};
    }
    if (command.accountId !== request.accountId || command.expires * 1000 < Date.now()) return fail("refused", "expired");
    if (!/^[a-f0-9]{32}$/.test(command.attempt) || !limits[command.kind] ||
        !Number.isInteger(command.limit) || command.limit < 1 || command.limit > 5)
      return fail("refused", "schema");
    const rule = limits[command.kind];
    if (rule.locked) return fail("refused", "permission");
    if (rule.today >= Math.min(rule.limit, command.limit)) return fail("deferred", "quota", {retryAfter: 300});
    let path, payload;
    const text = command.content;
    if (typeof text !== "string" || text.length > 500) return fail("refused", "schema");
    if (command.kind === "chat") {
      if (text.trim().split(/\s+/).length < 5 || !/^[1-9][0-9]{0,9}$/.test(command.subject)) return fail("refused", "schema");
      const channels = await channelsFor(profile);
      if (!channels.some(c => String(c.id) === command.subject)) return fail("refused", "channel");
      const slow = await get(`/api/messages/channels/${command.subject}/slow-mode-status`);
      if (slow.canSend !== true) return fail("deferred", "cooldown", {retryAfter: Math.max(30, Math.ceil((slow.remainingMs || 60000) / 1000))});
      // Compare the owner's recent messages across BOTH eligible channels.
      for (const channel of channels) {
        const history = await get(`/api/messages/channels/${channel.id}?limit=30`);
        if (!Array.isArray(history.messages) && !Array.isArray(history.data)) throw new Error("schema");
        const rows = history.messages || history.data;
        if (rows.some(m => String(m.sender?.id) === request.accountId && normal(m.content) === normal(text))) return fail("refused", "duplicate");
      }
      path = `/api/messages/channels/${command.subject}/messages`;
      payload = {content: text};
    } else {
      if (!/^[a-f0-9]{40}$/.test(command.subject)) return fail("refused", "schema");
      const torrent = await get(`/api/torrents/${command.subject}`);
      if (command.kind === "vote") {
        if (torrent.trust?.userVote) return fail("refused", "duplicate");
        if (torrent.trust?.canVote !== true) return fail("refused", "permission");
        if (!["approve", "disapprove"].includes(command.vote) || command.vote === "disapprove" && text.trim().length < 5) return fail("refused", "schema");
        path = `/api/torrents/${command.subject}/trust-vote`;
        payload = {vote: command.vote, reason: text || undefined};
      } else {
        if (text.trim().length < 3 || torrent.commentAccess?.canComment !== true || torrent.commentsLocked) return fail("refused", "permission");
        // canVote reflects completed/seed eligibility, but an existing vote is also evidence.
        if (torrent.trust?.canVote !== true && !torrent.trust?.userVote) return fail("refused", "permission");
        let complete = false;
        for (let page = 1; page <= 20; page++) {
          const comments = await get(`/api/torrents/${command.subject}/comments?page=${page}&limit=20&sort=recent`);
          if (!Array.isArray(comments.data) || !Number.isInteger(comments.meta?.totalPages)) throw new Error("schema");
          const own = rows => rows.some(c => String(c.author?.id) === request.accountId ||
            Array.isArray(c.replies) && own(c.replies));
          if (own(comments.data)) return fail("refused", "duplicate");
          if (page >= comments.meta.totalPages) {complete = true; break;}
        }
        if (!complete) return fail("refused", "unavailable");
        path = `/api/torrents/${command.subject}/comments`;
        payload = {content: text};
      }
    }
    // Last identity check immediately before the mutation. No token is exported.
    if (String((await get("/api/user/profile")).id) !== request.accountId) return fail("refused", "account");
    if (command.expires * 1000 < Date.now()) return fail("refused", "expired");
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    if (!token) return fail("refused", "token");
    sending = true;
    const response = await fetch(path, {method: "POST", credentials: "same-origin", redirect: "error",
      headers: {"Content-Type": "application/json", "csrf-token": token},
      body: JSON.stringify(payload), signal: AbortSignal.timeout(30000)});
    if (response.status === 429) {
      const raw = response.headers.get("retry-after");
      const retry = /^\d+$/.test(raw || "") ? Number(raw) : Math.ceil((Date.parse(raw) - Date.now()) / 1000);
      return fail("deferred", "rate", {retryAfter: Number.isFinite(retry) ? Math.max(60, retry) : 60});
    }
    if ([400, 401, 403, 404, 409, 422].includes(response.status))
      return fail("refused", [401, 403].includes(response.status) ? "auth" : "permission");
    if (!response.ok) return fail("uncertain", "network");
    const body = await response.json();
    if (body.success === false || body.error) return fail("uncertain", "receipt");
    const remote = command.kind === "comment" ? body.comment?.id : command.kind === "chat" ? body.messageId :
      body.trust && typeof body.trust.score === "number" && typeof body.trust.status === "string" ? command.subject : null;
    if (typeof remote !== "string" && !Number.isSafeInteger(remote)) return fail("uncertain", "receipt");
    return {outcome: "posted", remoteId: String(remote)};
  } catch (error) {
    if (sending) return fail("uncertain", "network");
    if (error.status === 429) return fail("deferred", "rate", {retryAfter: Number.isFinite(error.retryAfter) ? error.retryAfter : 60});
    return fail("refused", [401,403].includes(error.status) ? "auth" : error.message === "schema" ? "schema" : "network");
  }
}
