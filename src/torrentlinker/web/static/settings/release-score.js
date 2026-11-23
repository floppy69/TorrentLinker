/* ReleaseScore profiles live in the existing Search settings on both hosts. */
const scoreEditors = new Map();
function settingsReleaseScore(form) {
  const data = draft("release_score");
  if (!data.profiles) return;
  let editing = scoreEditors.get(environment.client_id) || data.active;
  if (!Object.hasOwn(data.profiles, editing)) editing = data.active;
  const selectEditing = (name) => {
    scoreEditors.set(environment.client_id, name);
    render();
  };
  const card = element("section", undefined, "settings-card");
  const heading = element("header", undefined, "score-section-heading");
  heading.append(element("h3", "ReleaseScore"));
  const community = element("details", undefined, "score-community-menu");
  const summary = element("summary", say("Community", "Communauté"));
  const communityActions = element("div", undefined, "score-community-actions");
  communityActions.append(button(say("Share profile","Partager le profil"),()=>communityShareDialog("release-score",{},data.profiles[editing])),button(say("Community profiles","Profils communautaires"),()=>communityBrowseDialog("release-score",async result=>{let name=result.metadata.title.slice(0,100),suffix=1;while(Object.hasOwn(data.profiles,name))name=`${result.metadata.title.slice(0,95)} ${suffix++}`;data.profiles[name]=result.data;selectEditing(name)})));
  community.append(summary, communityActions);
  community.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { community.open = false; summary.focus(); }
  });
  communityActions.addEventListener("click", (event) => {
    if (event.target.closest("button")) community.open = false;
  });
  heading.append(community);
  card.append(heading);
  const fields = element("div", undefined, "settings-fields");
  const profile = field(
    fields,
    say("Active profile", "Profil actif"),
    data,
    "active",
    "",
    Object.keys(data.profiles).map((n) => [n, n]),
  );
  profile.onchange = () =>
    guard(async () => {
      data.active = profile.value;
      if (await save()) render();
    });
  const threshold = field(
    fields,
    say("Media suggests releases from", "Médias propose les releases à partir de"),
    data,
    "threshold",
    "number",
  );
  Object.assign(threshold, { min: 0, max: 100, step: 1, required: true });
  threshold.title = say(
    "Media's tracker rows show films whose best c411 release scores at least this much.",
    "Les rangées du tracker dans Médias montrent les films dont la meilleure release c411 atteint ce score.",
  );
  const edit = field(
    fields,
    say("Edit profile", "Modifier le profil"),
    { editing },
    "editing",
    "",
    Object.keys(data.profiles).map((n) => [n, n]),
  );
  edit.onchange = () => selectEditing(edit.value);
  const name = field(fields, say("Profile name", "Nom du profil"), {}, "name");
  name.maxLength = 120;
  const actions = element("div", undefined, "settings-actions");
  const builtin = Object.hasOwn(snapshot.score_defaults, editing);
  const validName = () => {
    const n = name.value.trim();
    if (
      !n ||
      ["__proto__", "constructor", "prototype"].includes(n) ||
      Object.hasOwn(data.profiles, n)
    )
      throw Error(
        say(
          "Enter a new, unique profile name.",
          "Saisissez un nouveau nom de profil unique.",
        ),
      );
    return n;
  };
  actions.append(
    button(say("New", "Nouveau"), () => {
      const n = validName();
      data.profiles[n] = structuredClone(
        snapshot.score_defaults["HDLight 1080p"],
      );
      selectEditing(n);
    }),
  );
  actions.append(
    button(say("Duplicate", "Dupliquer"), () => {
      const n = validName();
      data.profiles[n] = structuredClone(data.profiles[editing]);
      selectEditing(n);
    }),
  );
  const rename = button(say("Rename", "Renommer"), () => {
    const n = validName();
    data.profiles[n] = data.profiles[editing];
    delete data.profiles[editing];
    if (data.active === editing) data.active = n;
    selectEditing(n);
  });
  const remove = button(say("Delete", "Supprimer"), () => {
    delete data.profiles[editing];
    if (data.active === editing) data.active = "HDLight 1080p";
    scoreEditors.delete(environment.client_id);
    render();
  });
  rename.disabled = remove.disabled = builtin;
  const reset = button(
    say("Reset built-in", "Réinitialiser le profil intégré"),
    () => {
      data.profiles[editing] = structuredClone(
        snapshot.score_defaults[editing],
      );
      render();
    },
  );
  reset.disabled = !builtin;
  actions.append(rename, remove, reset);
  card.append(fields, actions);
  const values = element("div", undefined, "settings-fields"),
    p = data.profiles[editing];
  const choices = [
    [
      "res",
      "Ideal resolution",
      "Résolution idéale",
      [
        ["1080", "1080p"],
        ["2160", "4K (2160p)"],
      ],
    ],
    [
      "basse",
      "Lower resolution",
      "Résolution inférieure",
      [
        ["penal", say("Penalized ×0.6", "Pénalisée ×0,6")],
        ["ok", say("Accepted", "Acceptée")],
      ],
    ],
    [
      "hdr",
      "HDR",
      "HDR",
      [
        ["sdr-req", say("SDR required", "SDR requis")],
        ["sdr-pref", say("SDR preferred", "SDR préféré")],
        ["indiff", say("No preference", "Indifférent")],
        ["pref", say("HDR preferred", "HDR préféré")],
        ["requis", say("HDR required", "HDR requis")],
      ],
    ],
    ...[
      ["dv", "Dolby Vision without HDR10", "Dolby Vision sans HDR10"],
      ["avi", "AVI file", "Fichier AVI"],
    ].map(([k, en, fr]) => [
      k,
      en,
      fr,
      [
        ["auto", say("According to equipment", "Selon l’équipement")],
        ["refuse", say("Refused", "Refusé")],
        ["deconseille", say("Discouraged ×0.9", "Déconseillé ×0,9")],
        ["ok", say("Accepted", "Accepté")],
      ],
    ]),
    [
      "codec",
      "H.265 / AV1",
      "H.265 / AV1",
      [
        ["requis", say("Required", "Requis")],
        ["pref", say("Preferred", "Préféré")],
        ["indiff", say("No preference", "Indifférent")],
      ],
    ],
    [
      "langue",
      "Audio language",
      "Langue audio",
      [
        ["vff", "VFF"],
        ["vf", "VFF / VFQ"],
        ["vo", "VO"],
        ["indiff", say("No preference", "Indifférente")],
      ],
    ],
    [
      "st",
      "French subtitles",
      "Sous-titres français",
      [
        ["indiff", say("No preference", "Indifférents")],
        ["pref", say("Preferred", "Préférés")],
        ["requis", say("Required", "Requis")],
      ],
    ],
    [
      "audio",
      "Ideal audio",
      "Audio idéal",
      [
        ["correct", "AC3 5.1 ~448 kb/s"],
        ["bon", "E-AC3 Atmos 768 kb/s"],
        ["sansperte", say("Lossless", "Sans perte")],
      ],
    ],
  ];
  for (const [k, en, fr, opts] of choices)
    field(values, say(en, fr), p, k, "", opts);
  for (const [k, en, fr, max, step] of [
    ["poidsAudio", "Audio weight (%)", "Poids audio (%)", 60, 5],
    [
      "cible",
      "Target (GB/hour, 0 = unlimited)",
      "Cible (Go/heure, 0 = illimité)",
      60,
      0.5,
    ],
    [
      "plafond",
      "Cap (GB/hour, 0 = unlimited)",
      "Plafond (Go/heure, 0 = illimité)",
      80,
      0.5,
    ],
  ]) {
    const input = field(values, say(en, fr), p, k, "number");
    input.min = 0;
    input.max = max;
    input.step = step;
  }
  card.append(values);
  const equipment = element("details"),
    ef = element("div", undefined, "settings-fields"),
    e = data.equipment;
  equipment.append(
    element("summary", say("Your equipment", "Votre équipement")),
    ef,
  );
  for (const [k, en, fr] of [
    ["ecran", "Screen model", "Modèle de l’écran"],
    ["appareil", "Playback device", "Appareil de lecture"],
  ]) {
    const input = field(ef, say(en, fr), e, k);
    input.maxLength = 120;
  }
  for (const [k, en, fr, min, max] of [
    ["taille", "Screen diagonal (inches)", "Diagonale (pouces)", 10, 300],
    ["distance", "Viewing distance (m)", "Distance de visionnage (m)", 0.3, 20],
  ]) {
    const input = field(ef, say(en, fr), e, k, "number");
    input.min = min;
    input.max = max;
    input.step = 0.1;
    input.oninput = () => {
      e[k] = input.value === "" ? null : Number(input.value);
    };
  }
  const unknown = ["", say("Unknown", "Inconnu")];
  field(ef, say("Screen definition", "Définition de l’écran"), e, "def", "", [
    unknown,
    ["1080", "1080p"],
    ["4k", "4K"],
  ]);
  for (const k of ["hdr", "dv", "av1", "dts", "avi"])
    field(
      ef,
      say(k.toUpperCase() + " support", "Prise en charge " + k.toUpperCase()),
      e,
      k,
      "",
      [
        unknown,
        ["oui", say("Supported", "Pris en charge")],
        ["non", say("Unsupported", "Non pris en charge")],
      ],
    );
  field(ef, say("Sound system", "Installation audio"), e, "son", "", [
    unknown,
    ["tv", "TV"],
    ["barre", say("Soundbar", "Barre de son")],
    ["51", "5.1"],
    ["atmos", "Atmos"],
  ]);
  field(ef, say("Priority", "Priorité"), e, "priorite", "", [
    unknown,
    ["place", say("Save space", "Économiser de la place")],
    ["equilibre", say("Balance", "Équilibre")],
    ["qualite", say("Quality", "Qualité")],
  ]);
  const save = async () => {
    if (
      ![...card.querySelectorAll("input,select")].every((n) =>
        n.reportValidity(),
      )
    )
      return false;
    const submitted = structuredClone(data),
      key = draftKey("release_score"),
      client = environment.client_id;
    const controls = [...card.querySelectorAll("input,select,button")].map(
      (n) => [n, n.disabled],
    );
    controls.forEach(([n]) => (n.disabled = true));
    try {
      const saved = await request("save", {
        group: "release_score",
        value: submitted,
      });
      if (client !== environment.client_id) return false;
      snapshot = saved;
      if (JSON.stringify(drafts.get(key)) === JSON.stringify(submitted))
        drafts.delete(key);
    } finally {
      controls.forEach(([n, disabled]) => (n.disabled = disabled));
    }
    $("settings-status").textContent = say(
      "ReleaseScore saved",
      "ReleaseScore enregistré",
    );
    return true;
  };
  equipment.append(
    button(
      say(
        "Save equipment and use its recommendation",
        "Enregistrer l’équipement et utiliser sa recommandation",
      ),
      async () => {
        if (!(await save())) return;
        const updated = draft("release_score");
        let n = say("My equipment", "Mon équipement"),
          suffix = 2;
        while (Object.hasOwn(updated.profiles, n))
          n = say("My equipment", "Mon équipement") + ` ${suffix++}`;
        updated.profiles[n] = snapshot.score_recommendation;
        updated.active = n;
        snapshot = await request("save", {
          group: "release_score",
          value: updated,
        });
        drafts.delete(draftKey("release_score"));
        render();
      },
    ),
  );
  card.append(
    equipment,
    button(
      say("Save ReleaseScore", "Enregistrer ReleaseScore"),
      async () => {
        if (await save()) render();
      },
      "primary",
    ),
  );
  form.append(card);
}
