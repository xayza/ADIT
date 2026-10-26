// ADIT frontend — talks to the stdlib JSON API. The AI panel calls only
// /api/ai/*; the AI itself never runs in this page, it only proposes a
// plan that the server validates before anything changes.
let project = null;
let selectedId = null;
let lastExport = null;
let lastDuration = 0;
let zoomPps = 60; // pixels per second on the timeline strip
let playheadTime = 0;
let waveformCache = {};
let dragState = null;
let suppressClick = false;

function fmtTime(t) {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}

const $ = (id) => document.getElementById(id);
const status = (msg) => { $("status").textContent = msg; };

async function api(path, method, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Lỗi ${res.status}`);
  return data;
}

const TEXT_PRESETS = {
  title: { font_size: 96, color: "#FFFFFF", position: "center" },
  subtitle: { font_size: 48, color: "#FFFFFF", position: "bottom" },
  caption: { font_size: 40, color: "#FFFF00", position: "bottom" },
  toplabel: { font_size: 56, color: "#FFFFFF", position: "top" },
};

function applyTextPreset(name, target) {
  const preset = TEXT_PRESETS[name];
  if (!preset) return;
  if (target === "add") {
    $("textFontSize").value = preset.font_size;
    $("textColor").value = preset.color;
    $("textPosition").value = preset.position;
  } else if (target === "props") {
    $("propFontSize").value = preset.font_size;
    $("propColor").value = preset.color;
    $("propPosition").value = preset.position;
  }
  status(`Đã áp preset chữ (cỡ ${preset.font_size}, màu ${preset.color}, vị trí ${preset.position}) — vẫn sửa được trước khi bấm Áp dụng.`);
}

function renderProjects(data) {
  const select = $("projectSelect");
  if (!select) return;
  const current = select.value;
  select.innerHTML = "";
  (data.projects || []).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name + (name === data.active_project ? " (đang mở)" : "");
    select.appendChild(opt);
  });
  select.value = data.active_project || current;
  if ($("btnUndo")) $("btnUndo").disabled = !data.can_undo;
  if ($("btnRedo")) $("btnRedo").disabled = !data.can_redo;
}

async function refresh() {
  const data = await api("/api/project", "GET");
  project = data.project;
  lastDuration = data.duration;
  renderMedia();
  renderTimeline(data.duration);
  renderProps();
  renderGlobalEdits();
  renderProjects(data);
}

function renderMedia() {
  const list = $("mediaList");
  list.innerHTML = "";
  (project.media || []).forEach((m) => {
    const div = document.createElement("div");
    div.className = "mediaItem";
    const thumb = m.thumbnail ? `<img src="/api/thumb/${encodeURIComponent(m.thumbnail)}" alt="">` : `<div style="width:56px;height:56px;background:#000;border-radius:6px"></div>`;
    div.innerHTML = `${thumb}<div><div class="name">${m.filename}</div><div class="meta">${m.type}${m.duration ? " • " + m.duration.toFixed(1) + "s" : ""}</div></div>`;
    const btn = document.createElement("button");
    btn.textContent = m.type === "audio" ? "Thêm nhạc" : "Thêm vào timeline";
    btn.onclick = () => addMediaToTimeline(m);
    div.appendChild(btn);
    const prev = document.createElement("button");
    prev.textContent = "Xem";
    prev.onclick = () => {
      if (m.type === "image") { $("previewImg").src = `/api/media-file/${encodeURIComponent(m.filename)}`; $("previewImg").style.display = "block"; $("preview").style.display = "none"; }
      else { $("preview").src = `/api/media-file/${encodeURIComponent(m.filename)}`; $("preview").style.display = "block"; $("previewImg").style.display = "none"; }
    };
    div.appendChild(prev);
    list.appendChild(div);
  });
}

function timelineEnd() {
  return Math.max(1, ...(project.clips || []).map((c) => c.start + c.duration));
}

async function addMediaToTimeline(m) {
  try {
    const start = timelineEndForTrack(0);
    const duration = m.type === "image" ? 3 : (m.duration || 3);
    const body = { type: m.type, source: m.filename, track: m.type === "audio" ? 2 : 0, start, duration, trim_in: 0, speed: 1, volume: 1, effect: "none" };
    if (m.type === "audio") body.start = 0;
    await api("/api/clips", "POST", body);
    status(`Đã thêm ${m.filename} vào timeline.`);
    await refresh();
  } catch (e) { status(e.message); }
}

function timelineEndForTrack(track) {
  const clips = (project.clips || []).filter((c) => c.track === track && c.type !== "audio");
  return clips.length ? Math.max(...clips.map((c) => c.start + c.duration)) : 0;
}

function setPlayhead(t) {
  const total = timelineEnd();
  playheadTime = Math.max(0, Math.min(total, t));
  const head = document.getElementById("playhead");
  if (head) head.style.left = `${playheadTime * zoomPps}px`;
  if ($("playheadLabel")) $("playheadLabel").textContent = `Playhead: ${fmtTime(playheadTime)}`;
  showProxyPreview(playheadTime);
}

function showProxyPreview(t) {
  // Proxy preview, NOT a rendered timeline preview: for a video/image
  // clip covering t, show that clip's own source positioned at the
  // corresponding source time; for a gap, show a black frame + timecode.
  const covering = (project.clips || [])
    .filter((c) => (c.type === "video" || c.type === "image") && c.start <= t && t < c.start + c.duration)
    .sort((a, b) => a.track - b.track || a.start - b.start);
  const clip = covering[0];
  const video = $("preview");
  const img = $("previewImg");
  const note = $("previewNote");
  if (!clip) {
    video.style.display = "none"; img.style.display = "none";
    note.style.display = "block";
    note.textContent = `Khung trống tại ${fmtTime(t)} — chưa có clip (xem trước đại diện, chưa phải bản render timeline). Bấm “Xem trước nhanh” để xem bản nháp đã render.`;
    return;
  }
  note.style.display = "none";
  if (clip.type === "image") {
    video.style.display = "none";
    img.src = `/api/media-file/${encodeURIComponent(clip.source)}`;
    img.style.display = "block";
    return;
  }
  img.style.display = "none";
  video.style.display = "block";
  const src = `/api/media-file/${encodeURIComponent(clip.source)}`;
  const target = clip.trim_in + (t - clip.start) * clip.speed;
  const seek = () => { try { video.currentTime = target; video.pause(); } catch (e) { /* ignore */ } };
  if (video.getAttribute("src") !== src) {
    video.src = src;
    video.addEventListener("loadedmetadata", seek, { once: true });
  } else if (video.readyState >= 1) {
    seek();
  } else {
    video.addEventListener("loadedmetadata", seek, { once: true });
  }
}

function drawWaveform(block, peaks) {
  if (!peaks || !peaks.length) return;
  const canvas = document.createElement("canvas");
  canvas.className = "waveCanvas";
  const w = Math.max(40, Math.floor(block.clientWidth || peaks.length));
  canvas.width = w;
  canvas.height = 26;
  const ctx = canvas.getContext("2d");
  const bars = Math.max(10, Math.floor(w / 3));
  const step = peaks.length / bars;
  ctx.fillStyle = "#8fd0ff";
  for (let i = 0; i < bars; i++) {
    let peak = 0;
    for (let j = Math.floor(i * step); j < Math.floor((i + 1) * step) && j < peaks.length; j++) peak = Math.max(peak, peaks[j]);
    const h = Math.max(2, peak * 26);
    ctx.fillRect(i * 3, (26 - h) / 2, 2, h);
  }
  block.appendChild(canvas);
}

async function loadWaveform(clip, block) {
  if (!clip.source) return;
  if (waveformCache[clip.source]) { drawWaveform(block, waveformCache[clip.source]); return; }
  try {
    const data = await api(`/api/waveform/${encodeURIComponent(clip.source)}`, "GET");
    if (data.peaks && data.peaks.length) {
      waveformCache[clip.source] = data.peaks;
      // The block may have been re-rendered meanwhile; only draw if it
      // is still the block for this clip.
      if (block.dataset.clipId === clip.id) drawWaveform(block, data.peaks);
    }
    // Empty peaks (no audio / generation failed) = bare block, by design.
  } catch (e) { /* waveform must never block the timeline */ }
}

function renderTimeline(duration) {
  lastDuration = duration;
  $("durationLabel").textContent = `Tổng thời lượng: ${duration.toFixed(1)}s`;
  const tracksEl = $("tracks");
  tracksEl.innerHTML = "";
  const tracks = [...new Set((project.clips || []).map((c) => c.track))].sort((a, b) => a - b);
  if (!tracks.length) tracks.push(0);
  // An empty next track row, so a clip can be dragged onto a new track.
  else if (!tracks.includes(Math.max(...tracks) + 1)) tracks.push(Math.max(...tracks) + 1);
  const total = timelineEnd();
  const inner = document.createElement("div");
  inner.className = "timelineInner";
  inner.style.width = `${Math.max(200, total * zoomPps)}px`;
  // Ruler: click to move the playhead (no page reload, no render).
  const ruler = document.createElement("div");
  ruler.className = "ruler";
  const tickStep = zoomPps >= 50 ? 1 : (zoomPps >= 20 ? 5 : 10);
  for (let t = 0; t <= total + 1e-6; t += tickStep) {
    const tick = document.createElement("div");
    tick.className = "rulerTick";
    tick.style.left = `${t * zoomPps}px`;
    tick.textContent = fmtTime(t);
    ruler.appendChild(tick);
  }
  ruler.addEventListener("click", (e) => {
    const rect = ruler.getBoundingClientRect();
    setPlayhead((e.clientX - rect.left) / zoomPps);
  });
  inner.appendChild(ruler);
  const tracksBox = document.createElement("div");
  tracksBox.className = "tracksBox";
  tracks.forEach((track) => {
    const trackEl = document.createElement("div");
    trackEl.className = "track";
    trackEl.dataset.track = track;
    const hasClips = (project.clips || []).some((c) => c.track === track);
    trackEl.innerHTML = `<div class="trackLabel">Track ${track}${hasClips ? "" : " (trống)"}</div>`;
    (project.clips || []).filter((c) => c.track === track).forEach((c) => {
      const block = document.createElement("div");
      block.className = `clipBlock ${c.type}` + (c.id === selectedId ? " selected" : "");
      block.dataset.clipId = c.id;
      block.style.left = `${c.start * zoomPps}px`;
      block.style.width = `${Math.max(24, c.duration * zoomPps)}px`;
      const label = document.createElement("div");
      label.className = "clipLabel";
      label.textContent = c.type === "text" ? `Chữ: ${c.text.slice(0, 20)}` : `${c.source || c.type} (${c.duration.toFixed(1)}s)`;
      block.appendChild(label);
      block.onclick = () => {
        if (suppressClick) { suppressClick = false; return; }
        selectedId = c.id; renderTimeline(duration); renderProps();
      };
      block.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        dragState = { id: c.id, startX: e.clientX, origStart: c.start, track: c.track, targetTrack: c.track, moved: false };
        const onMove = (ev) => {
          if (!dragState) return;
          const dx = ev.clientX - dragState.startX;
          // Cross-track: the track row under the mouse is the target.
          let targetTrack = dragState.track;
          document.querySelectorAll(".track").forEach((row) => {
            const rect = row.getBoundingClientRect();
            if (ev.clientY >= rect.top && ev.clientY <= rect.bottom) {
              targetTrack = parseInt(row.dataset.track, 10);
              row.classList.add("targetTrack");
            } else {
              row.classList.remove("targetTrack");
            }
          });
          dragState.targetTrack = targetTrack;
          if (Math.abs(dx) < 4 && targetTrack === dragState.track) return;
          dragState.moved = true;
          const newStart = Math.max(0, Math.round((dragState.origStart + dx / zoomPps) * 10) / 10);
          dragState.newStart = newStart;
          block.style.left = `${newStart * zoomPps}px`;
          block.classList.add("dragging");
          status(`Đang kéo clip tới track ${targetTrack} tại ${fmtTime(newStart)} — thả chuột để lưu.`);
        };
        const onUp = async () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          document.querySelectorAll(".track").forEach((row) => row.classList.remove("targetTrack"));
          if (!dragState) return;
          const state = dragState;
          dragState = null;
          block.classList.remove("dragging");
          if (!state.moved) return;
          suppressClick = true; // the click after drag must not re-select/re-render
          try {
            await api(`/api/clips/${state.id}/move`, "POST", { track: state.targetTrack, start: state.newStart });
            status(`Đã di chuyển clip tới track ${state.targetTrack} tại ${fmtTime(state.newStart)}.`);
            await refresh();
          } catch (err) {
            status(err.message); // overlap etc.: server rejected, revert by re-render
            await refresh();
          }
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      trackEl.appendChild(block);
      if (c.type === "audio" || c.type === "video") loadWaveform(c, block);
    });
    tracksBox.appendChild(trackEl);
  });
  inner.appendChild(tracksBox);
  const head = document.createElement("div");
  head.id = "playhead";
  head.className = "playhead";
  head.style.left = `${playheadTime * zoomPps}px`;
  inner.appendChild(head);
  tracksEl.appendChild(inner);
  if ($("zoomLabel")) $("zoomLabel").textContent = `${zoomPps}px/giây`;
  if ($("playheadLabel")) $("playheadLabel").textContent = `Playhead: ${fmtTime(playheadTime)}`;
}

function selectedClip() {
  return (project.clips || []).find((c) => c.id === selectedId) || null;
}

function renderProps() {
  const clip = selectedClip();
  if (!clip) { $("noSelection").style.display = "block"; $("propsForm").style.display = "none"; return; }
  $("noSelection").style.display = "none";
  $("propsForm").style.display = "block";
  $("propTrack").value = clip.track;
  $("propStart").value = clip.start;
  $("propDuration").value = clip.duration;
  $("propTrimIn").value = clip.trim_in;
  $("propSpeed").value = clip.speed;
  $("propVolume").value = clip.volume;
  $("propMuted").checked = clip.muted;
  $("propEffect").value = clip.effect;
  $("propFadeIn").value = clip.fade_in_seconds || 0;
  $("propFadeOut").value = clip.fade_out_seconds || 0;
  $("textProps").style.display = clip.type === "text" ? "block" : "none";
  $("propText").value = clip.text || "";
  $("propFontSize").value = clip.font_size || 48;
  $("propColor").value = clip.color || "#FFFFFF";
  $("propPosition").value = clip.position || "center";
  if (project.background_music) { $("musicSource").value = project.background_music.source; $("musicVolume").value = project.background_music.volume; }
}

$("uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("fileInput").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  status("Đang tải lên...");
  const res = await fetch("/api/media/upload", { method: "POST", body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { status(data.error || "Tải lên thất bại"); return; }
  status(`Đã tải lên ${data.media.filename}.`);
  $("fileInput").value = "";
  await refresh();
});

$("btnAddText").addEventListener("click", async () => {
  try {
    const text = $("textContent").value.trim();
    if (!text) { status("Nhập nội dung chữ trước."); return; }
    await api("/api/clips", "POST", { type: "text", source: "", track: 1, start: 0, duration: parseFloat($("textDuration").value) || 3, text, font_size: parseInt($("textFontSize").value) || 48, color: $("textColor").value || "#FFFFFF", position: $("textPosition").value || "center", effect: "none" });
    status("Đã thêm chữ vào timeline (track 1). Sửa vị trí/thời gian ở bảng thuộc tính.");
    await refresh();
  } catch (e) { status(e.message); }
});

$("btnApplyProps").addEventListener("click", async () => {
  const clip = selectedClip();
  if (!clip) return;
  try {
    await api(`/api/clips/${clip.id}`, "PATCH", {
      track: parseInt($("propTrack").value), start: parseFloat($("propStart").value),
      duration: parseFloat($("propDuration").value), trim_in: parseFloat($("propTrimIn").value),
      speed: parseFloat($("propSpeed").value), volume: parseFloat($("propVolume").value),
      muted: $("propMuted").checked, effect: $("propEffect").value,
      fade_in_seconds: parseFloat($("propFadeIn").value) || 0,
      fade_out_seconds: parseFloat($("propFadeOut").value) || 0,
      text: $("propText").value, font_size: parseInt($("propFontSize").value),
      color: $("propColor").value, position: $("propPosition").value,
    });
    status("Đã áp dụng thuộc tính.");
    await refresh();
  } catch (e) { status(e.message); }
});

$("btnCopyClip").addEventListener("click", async () => {
  const clip = selectedClip();
  if (!clip) return;
  try {
    const data = await api(`/api/clips/${clip.id}/copy`, "POST", {});
    selectedId = data.clip.id;
    status(`Đã sao chép clip thành clip mới tại ${fmtTime(data.clip.start)} trên track ${data.clip.track}.`);
    await refresh();
  } catch (e) { status(e.message); }
});

document.querySelectorAll(".textPresetBtn").forEach((btn) => {
  btn.addEventListener("click", () => {
    // Buttons in the Add-text panel set the new-text defaults; buttons
    // in the props panel set the selected clip's fields (still needs
    // "Áp dụng" to save, so presets stay editable starting values).
    const inProps = btn.closest("#propsForm");
    applyTextPreset(btn.dataset.preset, inProps ? "props" : "add");
  });
});

$("btnDeleteClip").addEventListener("click", async () => {
  const clip = selectedClip();
  if (!clip) return;
  try { await api(`/api/clips/${clip.id}`, "DELETE"); selectedId = null; status("Đã xóa clip."); await refresh(); }
  catch (e) { status(e.message); }
});

$("btnSplit").addEventListener("click", async () => {
  const clip = selectedClip();
  if (!clip) { status("Chọn một clip trên timeline trước."); return; }
  try {
    await api(`/api/clips/${clip.id}/split`, "POST", { at: parseFloat($("splitAt").value) });
    status("Đã tách clip.");
    await refresh();
  } catch (e) { status(e.message); }
});

async function splitAtPlayhead() {
  try {
    const data = await api("/api/timeline/split-at-playhead", "POST", { at: playheadTime, selected_clip_id: selectedId });
    status(`Đã tách clip tại playhead ${fmtTime(playheadTime)} thành 2 phần.`);
    await refresh();
  } catch (e) { status(e.message); }
}
$("btnSplitPlayhead").addEventListener("click", splitAtPlayhead);
// Keyboard shortcut: S splits at the playhead, but never while typing.
document.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (e.key === "s" || e.key === "S") { e.preventDefault(); splitAtPlayhead(); }
});

$("btnUndo").addEventListener("click", async () => {
  try { await api("/api/history/undo", "POST", {}); status("Đã hoàn tác thao tác thủ công gần nhất."); await refresh(); }
  catch (e) { status(e.message); }
});
$("btnRedo").addEventListener("click", async () => {
  try { await api("/api/history/redo", "POST", {}); status("Đã làm lại thao tác vừa hoàn tác."); await refresh(); }
  catch (e) { status(e.message); }
});

$("btnSwitchProject").addEventListener("click", async () => {
  const name = $("projectSelect").value;
  if (!name) return;
  try { await api("/api/projects/switch", "POST", { name }); selectedId = null; status(`Đã chuyển sang dự án ${name}.`); await refresh(); }
  catch (e) { status(e.message); }
});
$("btnCreateProject").addEventListener("click", async () => {
  const name = $("newProjectName").value.trim();
  if (!name) { status("Nhập tên dự án mới trước."); return; }
  try { await api("/api/projects", "POST", { name }); selectedId = null; $("newProjectName").value = ""; status(`Đã tạo và chuyển sang dự án ${name}.`); await refresh(); }
  catch (e) { status(e.message); }
});
$("btnRenameProject").addEventListener("click", async () => {
  const newName = $("renameProjectName").value.trim();
  if (!newName) { status("Nhập tên mới cho dự án trước."); return; }
  try {
    const data = await api("/api/projects/rename", "POST", { old: $("projectSelect").value, new_name: newName });
    selectedId = null; $("renameProjectName").value = ""; status(`Đã đổi tên dự án thành ${data.new}.`); await refresh();
  } catch (e) { status(e.message); }
});

$("btnSave").addEventListener("click", async () => {
  try { await api("/api/project/save", "POST", {}); status("Đã lưu dự án."); }
  catch (e) { status(e.message); }
});

async function doExport(draft, forceOverwrite) {
  try {
    status(draft ? "Đang render bản nháp…" : "Đang xuất video, vui lòng chờ...");
    const data = await api("/api/export", "POST", { draft, overwrite: !!forceOverwrite || $("chkOverwrite").checked, filename: draft ? "export_draft.mp4" : undefined });
    lastExport = data;
    $("preview").src = data.download;
    $("preview").style.display = "block";
    $("previewImg").style.display = "none";
    const ge = data.global_edits || {};
    const applied = [];
    if (ge.color === "better") applied.push("màu đẹp hơn (eq)");
    if (ge.volume_norm) applied.push("âm lượng ổn định (loudnorm)");
    if (ge.sharpen) applied.push("video nét hơn (unsharp)");
    status(`Xuất xong: ${data.output} (${data.width}x${data.height}, ${data.duration.toFixed(1)}s).` + (applied.length ? ` Chỉnh toàn cục đã áp: ${applied.join(", ")}.` : ""));
  } catch (e) { status(e.message); }
}
$("btnExportDraft").addEventListener("click", () => doExport(true));
$("btnExportFull").addEventListener("click", () => doExport(false));
if ($("btnQuickPreview")) $("btnQuickPreview").addEventListener("click", () => doExport(true, true));

// Timeline zoom (re-renders the strip only, no page reload, no API call).
function applyZoom(value) {
  zoomPps = Math.max(10, Math.min(200, parseInt(value, 10) || 60));
  renderTimeline(lastDuration);
}
if ($("zoomSlider")) $("zoomSlider").addEventListener("input", (e) => applyZoom(e.target.value));
if ($("btnZoomOut")) $("btnZoomOut").addEventListener("click", () => { const s = $("zoomSlider"); s.value = Math.max(10, parseInt(s.value, 10) - 10); applyZoom(s.value); });
if ($("btnZoomIn")) $("btnZoomIn").addEventListener("click", () => { const s = $("zoomSlider"); s.value = Math.min(200, parseInt(s.value, 10) + 10); applyZoom(s.value); });

// Global edits (real FFmpeg filters, not AI) — in-place, no page reload.
function renderGlobalEdits() {
  const ge = (project && project.global_edits) || { color: "none", volume_norm: false, sharpen: false };
  if ($("globalColor")) $("globalColor").value = ge.color;
  if ($("globalVolumeNorm")) $("globalVolumeNorm").checked = !!ge.volume_norm;
  if ($("globalSharpen")) $("globalSharpen").checked = !!ge.sharpen;
}
if ($("btnApplyGlobal")) $("btnApplyGlobal").addEventListener("click", async () => {
  try {
    const data = await api("/api/global-edits", "POST", {
      color: $("globalColor").value,
      volume_norm: $("globalVolumeNorm").checked,
      sharpen: $("globalSharpen").checked,
    });
    project.global_edits = data.global_edits;
    renderGlobalEdits();
    status("Đã lưu chỉnh sửa toàn cục. Nó sẽ áp dụng khi bạn xuất video (bản nháp hoặc bản chính).");
  } catch (e) { status(e.message); }
});
if ($("btnResetGlobal")) $("btnResetGlobal").addEventListener("click", async () => {
  try {
    const data = await api("/api/global-edits/reset", "POST", {});
    project.global_edits = data.global_edits;
    renderGlobalEdits();
    status("Đã bỏ mọi chỉnh sửa toàn cục (về mặc định).");
  } catch (e) { status(e.message); }
});

$("btnSetMusic").addEventListener("click", async () => {
  try { await api("/api/music", "POST", { source: $("musicSource").value.trim(), volume: parseFloat($("musicVolume").value) }); status("Đã đặt nhạc nền."); await refresh(); }
  catch (e) { status(e.message); }
});
$("btnClearMusic").addEventListener("click", async () => {
  try { await api("/api/music", "DELETE"); $("musicSource").value = ""; status("Đã xóa nhạc nền."); await refresh(); }
  catch (e) { status(e.message); }
});

async function refreshAiStatus() {
  try {
    const data = await api("/api/ai/status", "GET");
    if (data.ollama && data.ollama.reachable) {
      $("aiStatusLine").textContent = `Ollama local đã sẵn sàng tại ${data.ollama.host} (model mặc định: ${data.ollama.default_model}). AI miễn phí, không cần key.`;
    } else {
      $("aiStatusLine").textContent = `Ollama local chưa kết nối được tại ${data.ollama ? data.ollama.host : "http://localhost:11434"}. Chạy script scripts/setup_ollama_windows.ps1 một lần, rồi chạy 'ollama serve' nếu cần — hoặc chọn AI trả phí bên dưới và nhập key của bạn.`;
    }
    $("btnAiUndo").disabled = !data.has_backup;
  } catch (e) {
    $("aiStatusLine").textContent = `Không kiểm tra được trạng thái AI: ${e.message}`;
  }
}

function renderAiProposal(data) {
  const list = $("aiProposal");
  list.innerHTML = "";
  (data.descriptions || []).forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  });
  if (data.valid === false && data.errors) {
    $("aiMessage").textContent = "Đề xuất bị từ chối, không thay đổi gì: " + data.errors.join(" ");
  } else if (data.applied) {
    $("aiMessage").textContent = "Đã áp dụng trực tiếp lên timeline. Bấm Hoàn tác nếu muốn quay lại.";
  } else if (data.valid) {
    $("aiMessage").textContent = "AI đã đề xuất xong. Xem danh sách trên, rồi bấm Áp dụng nếu đồng ý.";
  }
}

$("btnAiAsk").addEventListener("click", async () => {
  const command = $("aiCommand").value.trim();
  if (!command) { $("aiMessage").textContent = "Nhập yêu cầu cho AI trước."; return; }
  $("aiMessage").textContent = "Đang hỏi AI, vui lòng chờ...";
  try {
    const data = await api("/api/ai/propose", "POST", {
      provider: $("aiProvider").value,
      model: $("aiModel").value.trim() || null,
      host: $("aiEndpoint").value.trim() || null,
      base_url: $("aiEndpoint").value.trim() || null,
      api_key: $("aiApiKey").value || null,
      command, selected_clip_id: selectedId,
      auto_apply: $("aiAutoApply").checked,
    });
    renderAiProposal(data);
    if (data.applied) await refresh();
    await refreshAiStatus();
  } catch (e) { $("aiMessage").textContent = e.message; }
});

$("btnAiApply").addEventListener("click", async () => {
  try {
    const data = await api("/api/ai/apply", "POST", {});
    $("aiProposal").innerHTML = "";
    $("aiMessage").textContent = "Đã áp dụng: " + (data.summary || []).join(" ");
    await refresh();
    await refreshAiStatus();
  } catch (e) { $("aiMessage").textContent = e.message; }
});

$("btnAiCancel").addEventListener("click", async () => {
  try { await api("/api/ai/cancel", "POST", {}); } catch (e) { /* ignore */ }
  $("aiProposal").innerHTML = "";
  $("aiMessage").textContent = "Đã hủy đề xuất, timeline không thay đổi.";
});

$("btnAiUndo").addEventListener("click", async () => {
  try {
    await api("/api/ai/undo", "POST", {});
    $("aiProposal").innerHTML = "";
    $("aiMessage").textContent = "Đã hoàn tác về trạng thái trước lần AI sửa gần nhất.";
    await refresh();
    await refreshAiStatus();
  } catch (e) { $("aiMessage").textContent = e.message; }
});

async function refreshModels() {
  try {
    const data = await api("/api/models", "GET");
    const list = $("modelList");
    list.innerHTML = "";
    const addRow = (m) => {
      const div = document.createElement("div");
      div.className = "mediaItem";
      const size = m.size ? ` • ${(m.size / 1048576).toFixed(0)} MB` : "";
      div.innerHTML = `<div><div class="name">${m.source}: ${m.name}</div><div class="meta">${size}</div></div>`;
      const del = document.createElement("button");
      del.textContent = "Xóa";
      del.onclick = async () => {
        if (!$("chkConfirmDeleteModel").checked) { $("modelMessage").textContent = "Tick ô xác nhận xóa model trước khi xóa."; return; }
        try {
          const path = m.source === "ollama" ? "/api/models/ollama/delete" : "/api/models/whisper/delete";
          await api(path, "POST", { name: m.name, confirm: true });
          $("modelMessage").textContent = `Đã xóa model ${m.name}.`;
          await refreshModels();
        } catch (e) { $("modelMessage").textContent = e.message; }
      };
      div.appendChild(del);
      list.appendChild(div);
    };
    (data.ollama.models || []).forEach(addRow);
    (data.whisper.models || []).forEach(addRow);
    if (data.ollama.error) $("modelMessage").textContent = data.ollama.error;
    if (!data.whisper.faster_whisper_available) $("modelMessage").textContent = "Chưa cài faster-whisper: chạy pip install faster-whisper (xem requirements-optional.txt) rồi tải model Whisper.";
    if (!$("modelList").children.length && !data.ollama.error) $("modelMessage").textContent = "Chưa có model nào được liệt kê.";
  } catch (e) { $("modelMessage").textContent = e.message; }
}

$("btnRefreshModels").addEventListener("click", refreshModels);

$("btnPullOllama").addEventListener("click", async () => {
  const name = $("ollamaModelName").value.trim();
  if (!name) { $("modelMessage").textContent = "Nhập tên model Ollama trước."; return; }
  $("modelMessage").textContent = "Đang tải model Ollama, có thể mất vài phút...";
  try { await api("/api/models/ollama/pull", "POST", { name }); $("modelMessage").textContent = `Đã tải model Ollama ${name}.`; await refreshModels(); }
  catch (e) { $("modelMessage").textContent = e.message; }
});

$("btnDownloadWhisper").addEventListener("click", async () => {
  $("modelMessage").textContent = "Đang tải model Whisper, có thể mất vài phút...";
  try { await api("/api/models/whisper/download", "POST", { model: $("whisperModelName").value }); $("modelMessage").textContent = "Đã tải model Whisper."; await refreshModels(); }
  catch (e) { $("modelMessage").textContent = e.message; }
});

$("btnTranscribe").addEventListener("click", async () => {
  const source = $("transcribeSource").value.trim();
  if (!source) { $("modelMessage").textContent = "Nhập tên file media trong dự án trước."; return; }
  $("modelMessage").textContent = "Đang phiên âm local, vui lòng chờ...";
  try {
    const data = await api("/api/transcribe", "POST", { source, model: $("transcribeModel").value });
    $("transcriptText").value = data.text || "";
    $("modelMessage").textContent = `Phiên âm xong: ${data.segments.length} đoạn, đã lưu transcript.txt / transcript.json.`;
  } catch (e) { $("modelMessage").textContent = e.message; }
});

async function runHelper(helper) {
  $("modelMessage").textContent = "Đang tạo gợi ý từ bản ghi...";
  try {
    const data = await api("/api/ai/helpers", "POST", {
      helper, provider: $("aiProvider").value,
      model: $("aiModel").value.trim() || null,
      host: $("aiEndpoint").value.trim() || null,
      base_url: $("aiEndpoint").value.trim() || null,
      api_key: $("aiApiKey").value || null,
    });
    $("helperText").value = data.result || "";
    $("modelMessage").textContent = data.truncated ? "Đã tạo gợi ý (bản ghi dài nên chỉ dùng 12.000 ký tự đầu)." : "Đã tạo gợi ý.";
  } catch (e) { $("modelMessage").textContent = e.message; }
}
$("btnChapters").addEventListener("click", () => runHelper("chapters"));
$("btnSummary").addEventListener("click", () => runHelper("summary"));
$("btnMetadata").addEventListener("click", () => runHelper("metadata"));

refresh().catch((e) => status(e.message));
refreshAiStatus();
refreshModels();
