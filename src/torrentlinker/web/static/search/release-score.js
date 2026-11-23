function scoreSummary(s) {
  return language === "fr" ? s.summary_fr : s.summary;
}
function releaseScorePill(row) {
  const s = row.release_score;
  if (!s) return document.createTextNode("");
  const text =
    s.score == null
      ? "?"
      : `${s.estimated ? "≈ " : ""}${s.score}${s.best ? " ⭐" : ""}`;
  const pill = button(
    text,
    () => details(row),
    `release-score-pill score-${s.color}`,
  );
  pill.title = `ReleaseScore · ${s.profile} · ${s.estimated ? say("Estimated", "Estimé") : "MediaInfo"} · ${scoreSummary(s)}`;
  pill.setAttribute("aria-label", `${text} · ${pill.title}`);
  return pill;
}
function releaseScoreDetails(score) {
  const box = element("details", undefined, "release-score-details");
  box.append(
    element(
      "summary",
      `ReleaseScore ${score.score == null ? "?" : `${score.estimated ? "≈ " : ""}${score.score}/100`} · ${score.profile}`,
    ),
  );
  box.append(element("p", scoreSummary(score)));
  box.append(
    element(
      "p",
      score.estimated
        ? say(
            "Estimated from listing facts. Missing facts remain unknown; no extra Indexer request.",
            "Estimation issue de la liste. Les faits manquants restent inconnus ; aucune requête indexeur supplémentaire.",
          )
        : say(
            "Calculated from the release’s MediaInfo.",
            "Calculé à partir du MediaInfo de la release.",
          ),
      "muted",
    ),
  );
  if (score.score != null) {
    box.append(
      element(
        "p",
        say(
          `Video ${score.video.note.toFixed(1)} · Audio ${score.audio.toFixed(1)} · Size factor ×${score.size_factor.toFixed(2)}`,
          `Vidéo ${score.video.note.toFixed(1)} · Audio ${score.audio.toFixed(1)} · Facteur taille ×${score.size_factor.toFixed(2)}`,
        ),
      ),
    );
    if (score.gb_per_hour != null)
      box.append(
        element(
          "p",
          `${score.gb_per_hour.toFixed(2)} ${say("GB/hour", "Go/heure")}`,
        ),
      );
    if (score.video_derived)
      box.append(
        element(
          "p",
          say(
            "Video bitrate derived from the overall bitrate.",
            "Débit vidéo déduit du débit global.",
          ),
          "muted",
        ),
      );
    const list = element("ul");
    for (const c of score.criteria.filter((c) => !c.ok || c.unknown))
      list.append(
        element(
          "li",
          `${language === "fr" ? c.label_fr : c.label}${c.unknown ? say(" · unknown, neutral", " · inconnu, neutre") : ` · ×${c.factor}`}`,
        ),
      );
    box.append(list);
  }
  return box;
}
let scoreProfilesKey = "";
function refreshScoreProfiles(value) {
  const node = $("release-score-profile");
  const key = JSON.stringify([
    value.score_profiles,
    value.score_active,
    language,
  ]);
  if (key === scoreProfilesKey || !value.score_profiles) return;
  scoreProfilesKey = key;
  node.replaceChildren(
    ...value.score_profiles.map((name) => {
      const option = element("option", name);
      option.value = name;
      return option;
    }),
  );
  node.value = value.score_active;
  node.setAttribute(
    "aria-label",
    say("ReleaseScore profile", "Profil ReleaseScore"),
  );
  node.onchange = () =>
    guard(async () => {
      node.disabled = true;
      try {
        await request("score-profile", { active: node.value });
        await api();
      } finally {
        node.disabled = false;
      }
    });
}

let scoreRevision = "";
async function refreshDetailScores(value) {
  if (!value.score_revision || value.score_revision === scoreRevision) return;
  scoreRevision = value.score_revision;
  for (const [hash, tab] of detailTabs) {
    if (!tab.document) continue;
    const score = await request("score-details", { hash });
    if (!detailTabs.has(hash)) continue;
    tab.document.release_score = score;
    const previous = tab.content.querySelector(".release-score-details");
    const next = releaseScoreDetails(score);
    next.open = previous?.open || false;
    if (previous) previous.replaceWith(next);
  }
}
