"use strict";
// Shared by the Media views: flags returns [text, strong] pairs for a video row.
// What the release name and the scan say about the file: the facts a viewer checks first.
function mediaFlags(item) {
  const name = ` ${String(item.release || "").replace(/[._]/g, " ")} `,
    found = [];
  const add = (text, strong = false) => {
    if (text && !found.some(([known]) => known === text))
      found.push([text, strong]);
  };
  const resolution = name.match(/\b(2160|1080|720|576|480)[pi]\b/i);
  if (resolution) add(`${resolution[1]}p`, Number(resolution[1]) >= 1080);
  else if (/\b(4K|UHD)\b/i.test(name)) add("2160p", true);
  if (/\b(DV|DoVi|Dolby ?Vision)\b/i.test(name)) add("Dolby Vision", true);
  if (/\bHDR10\+/i.test(name)) add("HDR10+", true);
  else if (/\bHDR(10)?\b/i.test(name)) add("HDR", true);
  const codec =
    item.codec ||
    (/\b(x265|h ?265|HEVC)\b/i.test(name)
      ? "HEVC"
      : /\b(x264|h ?264|AVC)\b/i.test(name)
        ? "H264"
        : /\bAV1\b/i.test(name)
          ? "AV1"
          : "");
  add(String(codec).toUpperCase());
  const audio = name.match(
    /\b(TrueHD|Atmos|DTS[- ]?HD(?: MA)?|DTS|E-?AC-?3|DDP|DD\+|AC-?3|AAC|FLAC|Opus)(?![a-z])/i,
  );
  const channels = name.match(/(?<!\d)([1-7])[ .]([01])(?!\d)/);
  const format = (value) => {
    const key = value.toLowerCase().replace(/[- ]/g, "");
    if (key.startsWith("dtshd")) return "DTS-HD MA";
    return (
      {
        truehd: "TrueHD",
        atmos: "Atmos",
        eac3: "E-AC-3",
        ddp: "E-AC-3",
        "dd+": "E-AC-3",
        ac3: "AC-3",
        opus: "Opus",
      }[key] || value.toUpperCase()
    );
  };
  if (audio)
    add(
      [
        format(audio[1]),
        channels ? `${channels[1]}.${channels[2]}` : "",
      ]
        .filter(Boolean)
        .join(" "),
    );
  if (/\bMULTI\b/i.test(name)) add("MULTI", true);
  else if (/\bVOSTFR\b/i.test(name)) add("VOSTFR");
  else if (/\b(VFF|VFQ|VFI|TRUEFRENCH|FRENCH)\b/i.test(name)) add("VF");
  return found;
}
