// ADIT frontend — talks to the stdlib JSON API. The AI panel calls only
// /api/ai/*; the AI itself never runs in this page, it only proposes a
// plan that the server validates before anything changes.
let project = null;
let selectedId = null;
let lastExport = null;

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

async function refresh() {
  const data = await api("/api/project", "GET");
  project = data.project;
  renderMedia();
  renderTimeline(data.duration);
  renderProps();
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

function renderTimeline(duration) {
  $("durationLabel").textContent = `Tổng thời lượng: ${duration.toFixed(1)}s`;
  const tracksEl = $("tracks");
  tracksEl.innerHTML = "";
  const tracks = [...new Set((project.clips || []).map((c) => c.track))].sort((a, b) => a - b);
  if (!tracks.length) tracks.push(0);
  const total = timelineEnd();
  tracks.forEach((track) => {
    const trackEl = document.createElement("div");
    trackEl.className = "track";
    trackEl.innerHTML = `<div class="trackLabel">Track ${track}</div>`;
    (project.clips || []).filter((c) => c.track === track).forEach((c) => {
      const block = document.createElement("div");
      block.className = `clipBlock ${c.type}` + (c.id === selectedId ? " selected" : "");
      block.style.left = `${(c.start / total) * 100}%`;
      block.style.width = `${Math.max(4, (c.duration / total) * 100)}%`;
      block.textContent = c.type === "text" ? `Chữ: ${c.text.slice(0, 20)}` : `${c.source || c.type} (${c.duration.toFixed(1)}s)`;
      block.onclick = () => { selectedId = c.id; renderTimeline(duration); renderProps(); };
      trackEl.appendChild(block);
    });
    tracksEl.appendChild(trackEl);
  });
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
    await api("/api/clips", "POST", { type: "text", source: "", track: 1, start: 0, duration: parseFloat($("textDuration").value) || 3, text, font_size: 48, color: "#FFFFFF", position: "center", effect: "none" });
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
      text: $("propText").value, font_size: parseInt($("propFontSize").value),
      color: $("propColor").value, position: $("propPosition").value,
    });
    status("Đã áp dụng thuộc tính.");
    await refresh();
  } catch (e) { status(e.message); }
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

$("btnSave").addEventListener("click", async () => {
  try { await api("/api/project/save", "POST", {}); status("Đã lưu dự án."); }
  catch (e) { status(e.message); }
});

async function doExport(draft) {
  try {
    status("Đang xuất video, vui lòng chờ...");
    const data = await api("/api/export", "POST", { draft, overwrite: $("chkOverwrite").checked });
    lastExport = data;
    $("preview").src = data.download;
    $("preview").style.display = "block";
    $("previewImg").style.display = "none";
    status(`Xuất xong: ${data.output} (${data.width}x${data.height}, ${data.duration.toFixed(1)}s).`);
  } catch (e) { status(e.message); }
}
$("btnExportDraft").addEventListener("click", () => doExport(true));
$("btnExportFull").addEventListener("click", () => doExport(false));

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
