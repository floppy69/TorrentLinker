/* Shared advanced Draft editor. Uses the same draft/revision and hosting flow as Upload. */
const preparation = (() => {
  const modal = document.createElement("dialog");
  modal.id = "preparation";
  modal.setAttribute("aria-labelledby", "prep-title");
  document.body.append(modal);
  let job = null,
    client = "",
    item = null,
    section = "details",
    busy = false,
    status = "",
    preview = null;
  const tabs = () => ({
    details: t("Détails", "Details"),
    files: t("Fichiers & NFO", "Files & NFO"),
    description: t("Description", "Description"),
    artwork: t("Illustrations", "Artwork"),
    models: t("Vue 3D", "3D view"),
    review: t("Révision", "Review"),
  });
  const button = (action, label, primary = false) =>
    `<button data-prep="${action}" ${busy ? "disabled" : ""} class="${primary ? "primary" : ""}">${label}</button>`;
  const input = (name, label, value) =>
    `<label for="prep-${name === "title" ? "title-field" : name}">${label}</label><input id="prep-${name === "title" ? "title-field" : name}" data-prep-field="${name}" value="${esc(value || "")}">`;
  function bbcode(value) {
    let out = esc(value);
    for (const tag of ["b", "i", "u", "s"])
      out = out
        .replace(new RegExp("\\[" + tag + "\\]", "gi"), "<" + tag + ">")
        .replace(new RegExp("\\[/" + tag + "\\]", "gi"), "</" + tag + ">");
    return out
      .replace(/\[center\]/gi, '<div style="text-align:center">')
      .replace(/\[\/center\]/gi, "</div>")
      .replace(/\n/g, "<br>");
  }
  async function showRichDescription(html) {
    const box = modal.querySelector("#prep-description-preview");
    if (!box) return;
    const template = document.createElement("template");
    template.innerHTML = html;
    const images = [...template.content.querySelectorAll("img")].map((img) => {
      const url = img.getAttribute("src");
      img.removeAttribute("src");
      img.alt = t("Chargement de l’image…", "Loading image…");
      return { img, url };
    });
    box.replaceChildren(template.content);
    for (const { img, url } of images.slice(0, 20)) {
      if (!img.isConnected) return;
      try {
        const r = await api("image-preview", { url });
        if (img.isConnected) img.src = r.src;
      } catch {
        img.alt = t("Image indisponible", "Image unavailable");
      }
    }
  }
  function changed() {
    item.dirty = true;
    item.reviewed = false;
    status = t("Modifications non enregistrées", "Unsaved changes");
    modal.querySelector("#prep-status").textContent = status;
  }
  function draw() {
    if (!item) return;
    const f = item.form,
      p = preview || item.preview || {},
      names = tabs();
    let body = "";
    if (section === "details")
      body = `<div class="prep-grid"><section>${input("title", t("Nom de la release"), f.title)}${button("original", t("Utiliser un nom original vérifié…", "Use a verified original name…"))}<label>${t("Catégorie")}</label><select data-prep-field="category">${categories.map((c) => `<option value="${c.id}" ${c.id === f.category ? "selected" : ""}>${esc(c.label ? uploadLabel(c.label) : c.name)}</option>`).join("")}</select><label>${t("Sous-catégorie")}</label><select data-prep-field="subcategory">${(p.subcategories || []).map((c) => `<option value="${c.id}" ${c.id === f.subcategory ? "selected" : ""}>${esc(c.label ? uploadLabel(c.label) : c.name)}</option>`).join("")}</select></section><section>${input("source", "Source", f.source)}<h3>${t("Options de la catégorie", "Category options")}</h3>${(p.options || []).map((o) => `<label>${esc(o.name)}<select data-prep-option="${o.id}" ${o.multiple ? "multiple" : ""}><option value="">${t("Choisir…")}</option>${o.values.map((v) => `<option value="${v.id}" ${(f.options?.[o.id] || []).includes(v.id) ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>`).join("")}${button("refresh-options", t("Actualiser les options", "Refresh options"))}<div class="callout">${t("Les résultats de recherche restent indicatifs.", "Search results remain advisory.")}</div></section></div>`;
    if (section === "files")
      body = `<div class="prep-grid"><section><h3>${t("Fichiers du torrent", "Torrent files")}</h3><table class="prep-table"><thead><tr><th>${t("Nom dans le torrent", "Name in torrent")}</th><th>${t("Taille", "Size")}</th></tr></thead><tbody>${(p.files || item.record?.files || []).map((r) => `<tr><td>${esc(r.torrent_path || r.path)}<br><small>${esc(r.local_path || r.source || "")}</small></td><td>${sizes(r.size)}</td></tr>`).join("")}</tbody></table>${button("archive", t("Décompresser une archive…", "Unpack an archive…"))}</section><section><label for="prep-nfo">NFO</label><textarea id="prep-nfo" data-prep-field="nfo">${esc(f.nfo || p.nfo || "")}</textarea>${button("reset-nfo", t("Régénérer depuis les fichiers…", "Regenerate from files…"))}</section></div>`;
    if (section === "description")
      body = `<div class="prep-grid"><section><label for="prep-description">${t("Description du partage · BBCode")}</label><textarea id="prep-description" data-prep-field="description">${esc(f.description || "")}</textarea>${button("reset-description", t("Rétablir le modèle…", "Reset from template…"))}</section><section><h3>${t("Aperçu", "Preview")}</h3><div id="prep-description-preview" class="prep-bbcode">${bbcode(f.description || "")}</div></section></div>`;
    if (section === "artwork")
      body = `<div class="prep-grid"><section><h3>${t("Illustration de présentation", "Presentation artwork")}</h3><div class="prep-artwork">${artwork ? `<img style="max-width:100%;max-height:300px" alt="${t("Illustration", "Artwork")}" src="${artwork}">` : f.image ? `<span>${esc(f.image)}</span>` : t("Aucune image hébergée", "No hosted image")}</div></section><section>${input("image", t("Lien direct de l’image hébergée"), f.image)}${button("image-preview", t("Actualiser l’aperçu", "Refresh preview"))}${button("host", t("Héberger avec Postimages…", "Host with Postimages…"))}<p class="notice">${t("Postimages · le lien est inclus dans la présentation à l’enregistrement.")}</p></section></div>`;
    if (section === "models") body = modelBody();
    if (section === "review")
      body = `<div class="callout"><b>${item.dirty ? t("Modifications non enregistrées", "Unsaved changes") : t("Révision enregistrée") + " " + item.revision}</b><p>${t("Toute modification demande un nouvel enregistrement et une nouvelle relecture.")}</p></div>${(p.refusals || []).map((x) => `<p class="error">${esc(uploadRuleText(x))}</p>`).join("")}${(p.warnings || []).map((x) => `<p class="notice">${esc(uploadRuleText(x))}</p>`).join("")}<pre>${esc(f.description || "")}</pre><label><input type="checkbox" id="prep-reviewed" ${item.reviewed ? "checked" : ""} ${item.dirty || busy || (p.refusals || []).length ? "disabled" : ""}>${t(" J’ai relu cette version, les fichiers et les avertissements.")}</label><p class="notice">${t("La publication finale reste manuelle sur c411.")}</p>`;
    const scroll = modal.scrollTop;
    modal.innerHTML = `<header class="prep-head"><div class="row between"><span class="eyebrow">${t("BROUILLON LOCAL · OUTILS DE PRÉPARATION", "LOCAL DRAFT · PREPARATION TOOLS")}</span>${button("close", "✕")}</div><h2 id="prep-title">${esc(f.title || item.name)}</h2><small>${t("Révision enregistrée")} ${item.revision}</small><nav class="prep-nav">${Object.entries(
      names,
    )
      .filter(([key]) => key !== "models" || f.category === 10)
      .map(
        ([key, label]) =>
          `<button data-prep-tab="${key}" class="${key === section ? "on" : ""}" ${busy ? "disabled" : ""}>${label}</button>`,
      )
      .join(
        "",
      )}</nav></header><div class="prep-body">${body}</div><footer class="prep-foot"><small id="prep-status" role="status">${esc(status)}</small><div class="row">${button("close", t("Retour au parcours", "Back to guided Upload"))}${button("save", t("Enregistrer le brouillon", "Save draft"), true)}</div></footer>`;
    modal.scrollTop = scroll;
    if (busy)
      modal.querySelectorAll("select").forEach((el) => (el.disabled = true));
  }
  async function prepare(form = item.form) {
    return api("prepare", { id: item.id, path: item.path, form });
  }
  async function open(i) {
    capture(i);
    client = environment.client;
    item = i;
    section = "details";
    status = "";
    preview = null;
    models = null;
    artwork = null;
    modelResult = null;
    mesh = null;
    piece = "";
    selectedModels = [];
    yaw = 45;
    pitch = 55;
    draw();
    modal.showModal();
    await run(async () => {
      preview = await prepare();
      draw();
    });
  }
  async function run(fn) {
    if (busy) return;
    busy = true;
    draw();
    try {
      await fn();
    } catch (e) {
      status = e.message;
      toast(e.message, "bad");
    } finally {
      busy = false;
      draw();
    }
  }
  function close() {
    if (busy) return;
    if (item.dirty) {
      confirm(
        () => t("Conserver vos modifications ?", "Keep your changes?"),
        () =>
          t(
            "Enregistrez avant de revenir au parcours.",
            "Save before returning to guided Upload.",
          ),
        async () => {
          await save();
          modal.close();
          render();
        },
      );
      return;
    }
    modal.close();
    render();
  }
  let acceptConfirmation = null;
  function confirm(title, text, accept) {
    acceptConfirmation = accept;
    dialog(
      () =>
        `<h2>${title()}</h2><p>${text()}</p><button id="prep-confirm" class="primary">${t("Confirmer", "Confirm")}</button>`,
    );
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest("#prep-confirm")) {
      $("dialog").close();
      run(acceptConfirmation);
    }
    const choice = e.target.closest("[data-original]");
    if (choice && modal.open) {
      item.form.title = preview.original_names[Number(choice.dataset.original)];
      changed();
      $("dialog").close();
      draw();
    }
    if (e.target.closest("#prep-extract")) {
      archivePreview.destination = $("prep-destination").value;
      $("dialog").close();
      run(extractArchive);
    }
    if (e.target.closest("#prep-browse")) {
      pickDestination().catch((e) => toast(e.message));
    }
    const folder = e.target.closest("[data-prep-folder]");
    if (folder)
      browseDestination(folder.dataset.prepFolder).catch((e) =>
        toast(e.message),
      );
    if (e.target.closest("#prep-use-folder")) {
      archivePreview.destination =
        $("prep-server-folder").value +
        "/" +
        archivePreview.destination.split("/").pop();
      archiveDialog();
    }
  });

  async function save() {
    const i = item,
      client = environment.client,
      form = JSON.stringify(i.form);
    const record = await api("save", {
      path: i.path,
      id: i.id,
      revision: i.revision,
      form: i.form,
    });
    if (client !== environment.client) return;
    const later = JSON.stringify(i.form) !== form ? i.form : null;
    item = adopt(record, i);
    if (later) item.form = later;
    item.dirty = !!later;
    item.reviewed = false;
    preview = await prepare();
    status = later
      ? t("Modifications non enregistrées", "Unsaved changes")
      : t("Enregistré", "Saved");
    render();
  }
  modal.addEventListener("input", (e) => {
    const name = e.target.dataset.prepField;
    if (name) {
      item.form[name] = ["category", "subcategory"].includes(name)
        ? Number(e.target.value)
        : e.target.value;
      if (name === "image") artwork = null;
      if (name === "nfo") item.form.nfo_origin = "original";
      item.description = item.form.description || "";
      changed();
      if (name === "description")
        modal.querySelector("#prep-description-preview").innerHTML = bbcode(
          e.target.value,
        );
    }
    if (e.target.dataset.prepOption) {
      item.form.options ||= {};
      item.form.options[e.target.dataset.prepOption] = [
        ...e.target.selectedOptions,
      ]
        .map((x) => Number(x.value))
        .filter(Boolean);
      changed();
    }
  });
  modal.addEventListener("change", (e) => {
    if (e.target.id === "prep-reviewed") item.reviewed = e.target.checked;
    if (["category", "subcategory"].includes(e.target.dataset.prepField)) {
      if (e.target.dataset.prepField === "category")
        item.form.subcategory = null;
      item.form.options = {};
      run(async () => {
        preview = await prepare();
        item.form.subcategory = preview.subcategory;
        item.form.options = preview.chosen;
      });
    }
  });
  modal.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.prepTab) {
      section = b.dataset.prepTab;
      draw();
      if (section === "description") {
        const text = item.form.description;
        try {
          const r = await api("presentation-preview", { form: item.form });
          if (section === "description" && item.form.description === text)
            showRichDescription(r.html);
        } catch (e) {
          status = e.message;
        }
      }
      return;
    }
    const a = b.dataset.prep;
    if (a === "close") {
      close();
      return;
    }
    if (a === "image-preview") {
      await run(async () => {
        const url = item.form.image;
        const response = await api("image-preview", { url });
        if (item.form.image === url) artwork = response.src;
      });
      return;
    }
    if (a === "export-artwork") {
      const asset = b.dataset.asset;
      await run(async () => {
        if (mode === "desktop")
          await api("save-artwork", { id: item.id, asset });
        else {
          const data = await api("asset-read", { id: item.id, asset });
          const link = document.createElement("a");
          link.href = data.src;
          link.download = "render.png";
          link.click();
        }
      });
      return;
    }
    if (a === "host") {
      openImageHost(item);
      return;
    }
    if (a === "refresh-options") {
      await run(async () => {
        preview = await api("refresh-options", {
          id: item.id,
          path: item.path,
          form: item.form,
        });
      });
      return;
    }
    if (a === "save") {
      await run(save);
      return;
    }
    if (a === "original") {
      const names = preview?.original_names || [];
      dialog(
        () =>
          `<h2>${t("Noms originaux vérifiés", "Verified original names")}</h2>${names.map((n, k) => `<button data-original="${k}">${esc(typeof n === "string" ? n : n.name || n.title || JSON.stringify(n))}</button>`).join("") || t("Aucun nom vérifié.", "No verified name.")}`,
      );
      return;
    }
    if (a?.startsWith("reset-")) {
      const key = a.slice(6);
      confirm(
        () => t("Remplacer le texte modifié ?", "Replace the edited text?"),
        () =>
          t(
            "Cette action remplace uniquement le texte de ce brouillon.",
            "This replaces only this draft’s text.",
          ),
        async () => {
          const p = await prepare({
            ...item.form,
            [key]: "",
            ...(key === "nfo" ? { nfo_origin: "" } : {}),
          });
          item.form[key] = p[key];
          if (key === "nfo") item.form.nfo_origin = p.nfo_origin;
          changed();
        },
      );
      return;
    }
    if (a === "archive") {
      await archiveOpen();
      return;
    }
    if (a === "camera") {
      yaw = 45;
      pitch = 55;
      draw();
      return;
    }
    if (a === "geometry") {
      await run(async () => {
        mesh = await tool("model-geometry", {
          id: item.id,
          path: item.path,
          file: piece,
        });
      });
      return;
    }
    if (a === "inspect" || a === "render")
      await run(() => modelAction(a, selectedModels, { yaw, pitch }));
  });
  modal.addEventListener("cancel", (e) => {
    e.preventDefault();
    close();
  });
  window.addEventListener("upload-environment", (e) => {
    if (!modal.open) return;
    if (e.detail.client !== client) {
      modal.close();
      item = null;
      return;
    }
    window.TLPanel.refreshForm(modal, draw);
  });
  let models = null,
    modelResult = null;
  let artwork = null;
  let mesh = null,
    piece = "",
    selectedModels = [],
    yaw = 45,
    pitch = 55;
  function modelBody() {
    return `<div class="prep-grid"><section><h3>${esc(piece) || t("Pièces 3D", "3D pieces")}</h3><div class="prep-artwork"><svg id="prep-mesh" viewBox="0 0 300 300" role="img" aria-label="${t("Aperçu 3D", "3D preview")}">${meshSVG()}</svg></div>${modelResult?.content?.map((x) => `<img style="max-width:100%" alt="${t("Rendu local", "Local render")}" src="data:image/png;base64,${x.data}">`).join("") || ""}</section><section>${button("inspect", t("Inspecter les pièces 3D", "Inspect 3D pieces"))}${models?.models.map((m) => `<label><input type="checkbox" data-model="${esc(m.file)}" ${selectedModels.includes(m.file) ? "checked" : ""} ${m.previewable ? "" : "disabled"}>${esc(m.file)}</label>`).join("") || ""}<label>${t("Pièce affichée", "Displayed piece")}</label><select id="prep-piece">${(
      models?.models || []
    )
      .filter((m) => m.previewable)
      .map(
        (m) =>
          `<option value="${esc(m.file)}" ${m.file === piece ? "selected" : ""}>${esc(m.file)}</option>`,
      )
      .join(
        "",
      )}</select>${button("geometry", t("Afficher la pièce", "Show piece"))}<label for="prep-yaw">${t("Rotation", "Rotation")}</label><input type="range" id="prep-yaw" min="-180" max="180" value="${yaw}"><label for="prep-pitch">${t("Inclinaison", "Tilt")}</label><input type="range" id="prep-pitch" min="0" max="180" value="${pitch}">${button("camera", t("Réinitialiser la caméra", "Reset camera"))}${button("render", t("Créer une planche de rendu", "Create a render sheet"))}${(modelResult?.artifacts || []).map((a) => `<button data-prep="export-artwork" data-asset="${esc(a.asset_id)}">${t("Enregistrer l’image…", "Save image…")}</button>`).join("")}<p class="notice">${t("Le rendu reste local jusqu’à son hébergement dans Illustrations.", "The render stays local until hosted from Artwork.")}</p></section></div>`;
  }
  function meshSVG() {
    if (!mesh) return "";
    const y = (yaw * Math.PI) / 180,
      p = (pitch * Math.PI) / 180,
      cy = Math.cos(y),
      sy = Math.sin(y),
      cp = Math.cos(p),
      sp = Math.sin(p);
    return mesh.triangles
      .map((tri) =>
        tri.map(([x, y, z]) => [
          cy * x + sy * y,
          -cp * sy * x + cp * cy * y + sp * z,
          sp * sy * x - sp * cy * y + cp * z,
        ]),
      )
      .sort(
        (a, b) =>
          a.reduce((n, v) => n + v[2], 0) - b.reduce((n, v) => n + v[2], 0),
      )
      .map(
        (tri) =>
          `<polygon points="${tri.map((v) => `${150 + v[0] * 210},${150 - v[1] * 210}`).join(" ")}" fill="var(--accent)" fill-opacity=".65" stroke="var(--bg)" stroke-width=".4"/>`,
      )
      .join("");
  }
  modal.addEventListener("input", (e) => {
    if (e.target.id === "prep-yaw" || e.target.id === "prep-pitch") {
      if (e.target.id === "prep-yaw") yaw = Number(e.target.value);
      else pitch = Number(e.target.value);
      modal.querySelector("#prep-mesh").innerHTML = meshSVG();
    }
  });
  modal.addEventListener("change", (e) => {
    if (e.target.dataset.model)
      selectedModels = [...modal.querySelectorAll("[data-model]:checked")].map(
        (e) => e.dataset.model,
      );
    if (e.target.id === "prep-piece") {
      piece = e.target.value;
      mesh = null;
    }
  });
  async function tool(action, body) {
    const g = generation;
    const started = await api("tool-start", { ...body, tool: action });
    job = started.id;
    while (g === generation) {
      const row = await api("tool-status", { job });
      if (row.status === "completed") {
        job = null;
        return row.result;
      }
      if (!["queued", "running"].includes(row.status)) {
        job = null;
        throw Error(row.error || row.status);
      }
      const el = modal.querySelector("#prep-status");
      if (el) {
        el.textContent =
          t("Opération en cours…", "Operation in progress…") +
          (row.progress?.total
            ? ` ${sizes(row.progress.done)} / ${sizes(row.progress.total)}`
            : "");
        const cancel = document.createElement("button");
        cancel.textContent = t("Annuler", "Cancel");
        cancel.onclick = () => api("tool-cancel", { job });
        if (row.progress?.cancellable !== false) el.append(cancel);
      }
      await new Promise((r) => setTimeout(r, 350));
    }
    job = null;
    throw Error(t("Le client cible a changé.", "The target client changed."));
  }
  async function modelAction(action, files, camera) {
    if (action === "inspect") {
      models = await tool("model-inspect", { path: item.path, id: item.id });
      selectedModels = models.models
        .filter((m) => m.previewable)
        .map((m) => m.file);
      piece = selectedModels[0] || "";
      if (piece)
        mesh = await tool("model-geometry", {
          id: item.id,
          path: item.path,
          file: piece,
        });
      return;
    }
    if (!files.length)
      throw Error(
        t("Sélectionnez au moins une pièce.", "Select at least one piece."),
      );
    modelResult = await tool("model-render", {
      path: item.path,
      id: item.id,
      files,
      cameras: Object.fromEntries(files.map((f) => [f, camera])),
    });
    item.form.assets = modelResult.artifacts.map((a) => a.asset_id);
    changed();
  }
  let archivePreview = null;
  async function extractArchive() {
    const r = await tool("archive-extract", {
      path: item.path,
      id: item.id,
      ...archivePreview,
    });
    toast(t("Extraction terminée", "Extraction complete"));
    modal.close();
    adopt(r.draft);
    await refresh(true);
  }
  async function pickDestination() {
    if (mode === "desktop") {
      const r = await api("pick", { type: "folder" });
      if (r.selected) {
        archivePreview.destination =
          r.selected + "/" + archivePreview.destination.split("/").pop();
        archiveDialog();
      }
    } else await browseDestination("");
  }
  async function browseDestination(path) {
    const r = await api("browse", { path });
    dialog(
      () =>
        `<h2>${t("Choisir un dossier", "Choose a folder")}</h2><input id="prep-server-folder" value="${esc(r.path)}" readonly>${r.parent ? `<button data-prep-folder="${esc(r.parent)}">↑</button>` : ""}${r.folders.map((f) => `<button data-prep-folder="${esc(f)}">${esc(f)}</button>`).join("")}<button id="prep-use-folder" ${r.path ? "" : "disabled"}>${t("Choisir ce dossier", "Use this folder")}</button>`,
    );
  }
  function archiveDialog() {
    const result = archivePreview;
    dialog(
      () =>
        `<h2>${t("Décompresser une archive…", "Unpack an archive…")}</h2><label for="prep-destination">${t("Dossier de destination", "Destination folder")}</label><input id="prep-destination" value="${esc(result.destination)}"><button id="prep-browse">${t("Parcourir…", "Browse…")}</button><p>${sizes(result.size)} · ${result.files} ${t("Fichiers", "Files")} · ${sizes(result.free)} ${t("disponibles", "available")}</p><p>${t("Les fichiers d’origine sont conservés.", "Original files are preserved.")}</p><button id="prep-extract">${t("Confirmer", "Confirm")}</button>`,
    );
  }
  async function archiveOpen() {
    status = t("Préparation des archives en cours", "Reading archive details");
    draw();
    await run(async () => {
      const result = await tool("archive-preview", {
        path: item.path,
        id: item.id,
      });
      archivePreview = result;
      archiveDialog();
    });
  }
  return {
    open,
    async seed(i) {
      item = i;
      client = environment.client;
      section = "review";
      draw();
      modal.showModal();
      await run(async () => {
        await tool("seed-upload", {
          id: i.id,
          path: i.path,
          revision: i.revision,
        });
        status = t("Vérification lancée.", "Verification started.");
      });
    },
    refresh() {
      artwork = null;
      if (modal.open) draw();
    },
  };
})();
