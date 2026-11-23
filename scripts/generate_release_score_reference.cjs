// Generate offline reference results from the MIT upstream checkout.
// Usage: node scripts/generate_release_score_reference.cjs /path/to/releasescore
const fs = require("fs");
const path = require("node:path");
const cp = require("node:child_process");
const root = path.resolve(process.argv[2] || "");
const pinned = "cb65746203871d29a04acdf5447c3f662ba072cb";
if (
  cp
    .execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {
      encoding: "utf8",
    })
    .trim() !== pinned
)
  throw Error("Use the pinned ReleaseScore 0.3.0 checkout");
const n = require(path.join(root, "releasescore/moteur/note.js")).v2;
const samples = [];
for (const codec of ["H.264", "H.265", "AV1", "XviD"])
  for (const res of [
    [3840, 2160],
    [1920, 1080],
    [1440, 1080],
    [1280, 720],
    [720, 576],
  ])
    for (const hdr of ["SDR", "HDR10", "DV seul"]) {
      const i = samples.length;
      samples.push({
        w: res[0],
        h: res[1],
        codec,
        video: [1, 3, 10][i % 3],
        hdr,
        bits: i % 2 ? 10 : 8,
        taille: [2e9, 5e9, 20e9][i % 3],
        duree: 120,
        estime: true,
        avi: codec === "XviD",
        pistes: [
          {
            format: ["AC-3", "E-AC-3 JOC", "DTS XLL X", "AAC"][i % 4],
            canaux: [2, 6, 8][i % 3],
            debit: i % 2 ? 768 : null,
            langue: ["vff", "vo", "?"][i % 3],
          },
        ],
        ...(i % 2 ? { st: [] } : {}),
        ...(i % 5 === 0
          ? { lib: "x265", enc: { subme: 4, me: 3, rd: 4, ref: 5 } }
          : {}),
      });
    }
const cases = [];
for (const equipment of [{}, { dv: "non", avi: "non", av1: "non", dts: "non" }])
  for (const [name, r] of Object.entries(n.PROFILS))
    for (const facts of samples) {
      n.equipement(equipment);
      const j = n.juger(facts, r, n.ideal(r));
      cases.push({
        profile: name,
        equipment,
        facts,
        expected: {
          value: j.globale,
          video: j.NV.note,
          audio: j.NA,
          size_factor: j.fPoids,
          criteria_factor: j.fCrit,
          video_share: j.pv,
          audio_share: j.pa,
        },
      });
    }
fs.mkdirSync("tests/fixtures/release_score", { recursive: true });
fs.writeFileSync(
  "tests/fixtures/release_score/rapide.json",
  JSON.stringify(
    {
      version: "0.3.0",
      commit: "cb65746203871d29a04acdf5447c3f662ba072cb",
      cases,
    },
    null,
    2,
  ) + "\n",
);
