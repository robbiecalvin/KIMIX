const HEADER_W = 220;
const ROW_H = 54;
const CLIP_H = 34;
const TOP_MARGIN = 10;
const FINAL_CONTAINER_H = 78;
const FINAL_ROW_PAD = 12;
const SECTION_GAP = 10;
const SNAP_MS = 250;
const HISTORY_LIMIT = 25;
const STORAGE_KEY = "kimix-web-v2";

const state = {
  projects: {},
  currentProjectName: null,
  selectedTrack: -1,
  selectedClip: -1,
  playheadMs: 0,
  currentPosMs: 0,
  pxPerSec: 100,
  drag: null,
  rowDrag: null,
  clipboard: null,
  bufferMap: new Map(),
  nextBufferId: 1,
  nextClipId: 1,
  audioContext: null,
  playback: {
    isPlaying: false,
    startedAt: 0,
    startPosMs: 0,
    speed: 1,
    stopAtMs: 0,
    sources: [],
    timer: null,
  },
  autosaveTimer: null,
  loading: false,
};

const ui = {
  modeButtons: [...document.querySelectorAll(".mode-btn")],
  panels: {
    now: document.getElementById("panel-now"),
    playlist: document.getElementById("panel-playlist"),
    editor: document.getElementById("panel-editor"),
  },
  newProjectBtn: document.getElementById("new-project-btn"),
  openProjectInput: document.getElementById("open-project-input"),
  saveProjectBtn: document.getElementById("save-project-btn"),
  undoBtn: document.getElementById("undo-btn"),
  redoBtn: document.getElementById("redo-btn"),
  projectSelect: document.getElementById("project-select"),
  addAudioInput: document.getElementById("add-audio-input"),
  recordBtn: document.getElementById("record-btn"),
  playPauseBtn: document.getElementById("play-pause-btn"),
  stopBtn: document.getElementById("stop-btn"),
  exportBtn: document.getElementById("export-btn"),
  muteTrackBtn: document.getElementById("mute-track-btn"),
  seekSlider: document.getElementById("seek-slider"),
  durationLabel: document.getElementById("duration-label"),
  positionLabel: document.getElementById("position-label"),
  startInput: document.getElementById("start-input"),
  endInput: document.getElementById("end-input"),
  speedSelect: document.getElementById("speed-select"),
  pitchCheckbox: document.getElementById("pitch-checkbox"),
  fadeCheckbox: document.getElementById("fade-checkbox"),
  fadeInput: document.getElementById("fade-input"),
  boostSelect: document.getElementById("boost-select"),
  noiseCheckbox: document.getElementById("noise-checkbox"),
  reverseBtn: document.getElementById("reverse-btn"),
  trackVolSlider: document.getElementById("track-volume-slider"),
  trackVolValue: document.getElementById("track-volume-value"),
  clipVolSlider: document.getElementById("clip-volume-slider"),
  clipVolValue: document.getElementById("clip-volume-value"),
  zoomInput: document.getElementById("zoom-input"),
  zoomValue: document.getElementById("zoom-value"),
  statusLabel: document.getElementById("status-label"),
  cutBtn: document.getElementById("cut-btn"),
  copyBtn: document.getElementById("copy-btn"),
  pasteBtn: document.getElementById("paste-btn"),
  deleteBtn: document.getElementById("delete-btn"),
  splitBtn: document.getElementById("split-btn"),
  timelineScroll: document.getElementById("timeline-scroll"),
  timelineCanvas: document.getElementById("timeline-canvas"),
};
ui.ctx = ui.timelineCanvas.getContext("2d");

init();

function init() {
  wireModeButtons();
  wireEditorControls();
  loadAutosave();
  if (!state.currentProjectName) {
    createProject("Project 1");
  }
  refreshProjectSelect();
  switchProject(state.currentProjectName);
  renderTimeline();
}

function wireModeButtons() {
  ui.modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      ui.modeButtons.forEach((item) => item.classList.toggle("active", item === btn));
      Object.entries(ui.panels).forEach(([name, panel]) => {
        panel.classList.toggle("active", name === btn.dataset.mode);
      });
    });
  });
}

function wireEditorControls() {
  ui.newProjectBtn.addEventListener("click", onNewProject);
  ui.openProjectInput.addEventListener("change", onOpenProjectFile);
  ui.saveProjectBtn.addEventListener("click", onSaveProjectAs);
  ui.undoBtn.addEventListener("click", undoLast);
  ui.redoBtn.addEventListener("click", redoLast);
  ui.projectSelect.addEventListener("change", () => switchProject(ui.projectSelect.value));
  ui.addAudioInput.addEventListener("change", onAddAudioFiles);
  ui.playPauseBtn.addEventListener("click", togglePlayPause);
  ui.stopBtn.addEventListener("click", stopAndRewind);
  ui.exportBtn.addEventListener("click", exportMixWav);
  ui.muteTrackBtn.addEventListener("click", toggleSelectedTrackMute);
  ui.seekSlider.addEventListener("input", () => seekTo(Number(ui.seekSlider.value)));
  ui.reverseBtn.addEventListener("click", reverseSelectedClip);
  ui.trackVolSlider.addEventListener("input", onTrackVolumeChanged);
  ui.clipVolSlider.addEventListener("input", onClipVolumeChanged);
  ui.zoomInput.addEventListener("input", onZoomChanged);
  ui.cutBtn.addEventListener("click", cutSelection);
  ui.copyBtn.addEventListener("click", copySelection);
  ui.pasteBtn.addEventListener("click", pasteClipboard);
  ui.deleteBtn.addEventListener("click", deleteSelection);
  ui.splitBtn.addEventListener("click", splitSelectedClip);

  ui.timelineCanvas.addEventListener("mousedown", onTimelineMouseDown);
  ui.timelineCanvas.addEventListener("mousemove", onTimelineMouseMove);
  window.addEventListener("mouseup", onTimelineMouseUp);
}

function createProject(name) {
  const projectName = uniqueProjectName(name);
  state.projects[projectName] = {
    name: projectName,
    revision: 0,
    tracks: [finalTrack()],
    undo: [],
    redo: [],
  };
  state.currentProjectName = projectName;
  scheduleAutosave();
  return state.projects[projectName];
}

function finalTrack() {
  return { name: "Final Product", isFinal: true, muted: false, volumeDb: 0, clips: [] };
}

function uniqueProjectName(base) {
  if (!state.projects[base]) return base;
  let idx = 2;
  while (state.projects[`${base} (${idx})`]) idx += 1;
  return `${base} (${idx})`;
}

function currentProject() {
  return state.projects[state.currentProjectName] || null;
}

function ensureFinalTrack(project) {
  if (!project) return;
  let idx = project.tracks.findIndex((t) => t.isFinal || (t.name || "").toLowerCase() === "final product");
  if (idx < 0) {
    project.tracks.unshift(finalTrack());
    idx = 0;
  }
  if (idx !== 0) {
    const [track] = project.tracks.splice(idx, 1);
    track.name = "Final Product";
    track.isFinal = true;
    project.tracks.unshift(track);
  }
  project.tracks[0].isFinal = true;
  project.tracks[0].name = "Final Product";
  for (let i = 1; i < project.tracks.length; i += 1) project.tracks[i].isFinal = false;
}

function pruneEmptyTracks(project) {
  if (!project) return false;
  const before = project.tracks.length;
  project.tracks = project.tracks.filter((t, idx) => idx === 0 || t.clips.length > 0);
  ensureFinalTrack(project);
  return project.tracks.length !== before;
}

function pushUndoState() {
  if (state.loading) return;
  const project = currentProject();
  if (!project) return;
  project.undo.push(projectSnapshot(project));
  if (project.undo.length > HISTORY_LIMIT) project.undo.shift();
  project.redo = [];
}

function projectSnapshot(project) {
  return JSON.parse(JSON.stringify({
    name: project.name,
    revision: project.revision,
    tracks: project.tracks,
  }));
}

function restoreSnapshot(snapshot) {
  const project = currentProject();
  if (!project) return;
  project.tracks = snapshot.tracks;
  project.revision = snapshot.revision;
  ensureFinalTrack(project);
  state.selectedTrack = -1;
  state.selectedClip = -1;
}

function undoLast() {
  const project = currentProject();
  if (!project || project.undo.length === 0) return;
  project.redo.push(projectSnapshot(project));
  const prev = project.undo.pop();
  restoreSnapshot(prev);
  markProjectDirty(false);
  refreshAll();
}

function redoLast() {
  const project = currentProject();
  if (!project || project.redo.length === 0) return;
  project.undo.push(projectSnapshot(project));
  const next = project.redo.pop();
  restoreSnapshot(next);
  markProjectDirty(false);
  refreshAll();
}

function onNewProject() {
  const name = window.prompt("Project name:");
  if (!name) return;
  const trimmed = name.trim();
  if (!trimmed) return;
  createProject(trimmed);
  refreshProjectSelect();
  switchProject(state.currentProjectName);
  setStatus(`Created ${state.currentProjectName}.`);
}

function refreshProjectSelect() {
  const names = Object.keys(state.projects);
  ui.projectSelect.innerHTML = "";
  names.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    ui.projectSelect.appendChild(opt);
  });
  if (state.currentProjectName) ui.projectSelect.value = state.currentProjectName;
}

function switchProject(name) {
  stopPlayback();
  if (!name || !state.projects[name]) return;
  state.currentProjectName = name;
  const project = currentProject();
  ensureFinalTrack(project);
  state.selectedTrack = -1;
  state.selectedClip = -1;
  state.playheadMs = 0;
  state.currentPosMs = 0;
  ui.startInput.value = "0.0";
  ui.endInput.value = formatSeconds(totalDurationMs());
  refreshAll();
}

async function onAddAudioFiles(e) {
  const project = currentProject();
  if (!project) return;
  const files = [...(e.target.files || [])];
  if (!files.length) return;
  pushUndoState();
  stopPlayback();
  ensureFinalTrack(project);
  const audioContext = getAudioContext();
  for (const file of files) {
    try {
      const arr = await file.arrayBuffer();
      const decoded = await audioContext.decodeAudioData(arr.slice(0));
      const bufferId = registerBuffer(decoded);
      project.tracks.push({
        name: `Track ${project.tracks.length}`,
        muted: false,
        volumeDb: 0,
        isFinal: false,
        clips: [buildClip(file.name, bufferId, 0, false)],
      });
    } catch (_err) {
      setStatus(`Failed to load ${file.name}.`);
    }
  }
  e.target.value = "";
  markProjectDirty();
  refreshAll();
}

function registerBuffer(audioBuffer) {
  const id = state.nextBufferId++;
  state.bufferMap.set(id, audioBuffer);
  return id;
}

function buildClip(name, bufferId, startMs, spliced) {
  const buffer = state.bufferMap.get(bufferId);
  return {
    clipId: state.nextClipId++,
    name,
    bufferId,
    startMs: Math.max(0, Math.floor(startMs)),
    spliced: Boolean(spliced),
    volumeDb: 0,
    waveform: computeWaveform(buffer, 180),
  };
}

function computeWaveform(buffer, bins) {
  if (!buffer) return new Array(bins).fill(0);
  const channel = buffer.getChannelData(0);
  const block = Math.max(1, Math.floor(channel.length / bins));
  const values = [];
  for (let i = 0; i < bins; i += 1) {
    const start = i * block;
    const end = Math.min(channel.length, start + block);
    let peak = 0;
    for (let j = start; j < end; j += 1) peak = Math.max(peak, Math.abs(channel[j]));
    values.push(peak);
  }
  return values;
}

function totalDurationMs() {
  const project = currentProject();
  if (!project) return 0;
  let maxMs = 0;
  project.tracks.forEach((track) => {
    track.clips.forEach((clip) => {
      const dur = clipDurationMs(clip);
      maxMs = Math.max(maxMs, clip.startMs + dur);
    });
  });
  return maxMs;
}

function clipDurationMs(clip) {
  const buffer = state.bufferMap.get(clip.bufferId);
  return buffer ? Math.floor(buffer.duration * 1000) : 0;
}

function formatSeconds(ms) {
  return (ms / 1000).toFixed(2);
}

function parseTimeMs(text) {
  const value = String(text || "").trim();
  if (!value) throw new Error("Time is empty.");
  if (value.includes(":")) {
    const parts = value.split(":");
    if (parts.length !== 2) throw new Error("Use mm:ss or seconds.");
    const mins = Number(parts[0]);
    const secs = Number(parts[1]);
    if (Number.isNaN(mins) || Number.isNaN(secs)) throw new Error("Invalid time.");
    return Math.max(0, Math.floor((mins * 60 + secs) * 1000));
  }
  const secs = Number(value);
  if (Number.isNaN(secs)) throw new Error("Invalid time.");
  return Math.max(0, Math.floor(secs * 1000));
}

function getSelectionRange() {
  const start = parseTimeMs(ui.startInput.value);
  const end = parseTimeMs(ui.endInput.value);
  if (end < start) throw new Error("End time must be >= start time.");
  return { start, end };
}

function selectedClipRef() {
  const project = currentProject();
  if (!project) return null;
  if (state.selectedTrack < 0 || state.selectedClip < 0) return null;
  if (state.selectedTrack >= project.tracks.length) return null;
  const track = project.tracks[state.selectedTrack];
  if (state.selectedClip >= track.clips.length) return null;
  return { track, clip: track.clips[state.selectedClip], trackIdx: state.selectedTrack, clipIdx: state.selectedClip };
}

function copySelection() {
  const ref = selectedClipRef();
  if (!ref) return setStatus("Select a clip first.");
  try {
    const { start, end } = getSelectionRange();
    const interStart = Math.max(start, ref.clip.startMs);
    const interEnd = Math.min(end, ref.clip.startMs + clipDurationMs(ref.clip));
    if (interEnd <= interStart) return setStatus("Selection does not overlap selected clip.");
    const localStart = interStart - ref.clip.startMs;
    const localEnd = interEnd - ref.clip.startMs;
    const srcBuffer = state.bufferMap.get(ref.clip.bufferId);
    const sliced = sliceBuffer(srcBuffer, localStart, localEnd);
    const bufferId = registerBuffer(sliced);
    state.clipboard = {
      name: `${ref.clip.name} (copy)`,
      bufferId,
      volumeDb: ref.clip.volumeDb || 0,
    };
    setStatus("Copied selection.");
  } catch (err) {
    setStatus(String(err.message || err));
  }
}

function cutSelection() {
  const ref = selectedClipRef();
  if (!ref) return setStatus("Select a clip first.");
  try {
    pushUndoState();
    const { start, end } = getSelectionRange();
    const interStart = Math.max(start, ref.clip.startMs);
    const interEnd = Math.min(end, ref.clip.startMs + clipDurationMs(ref.clip));
    if (interEnd <= interStart) return setStatus("Selection does not overlap selected clip.");
    const localStart = interStart - ref.clip.startMs;
    const localEnd = interEnd - ref.clip.startMs;
    const srcBuffer = state.bufferMap.get(ref.clip.bufferId);
    const copied = sliceBuffer(srcBuffer, localStart, localEnd);
    state.clipboard = { name: `${ref.clip.name} (cut)`, bufferId: registerBuffer(copied), volumeDb: ref.clip.volumeDb || 0 };
    replaceClipWithCut(ref, localStart, localEnd, interStart, interEnd);
    markProjectDirty();
    refreshAll();
  } catch (err) {
    setStatus(String(err.message || err));
  }
}

function deleteSelection() {
  const ref = selectedClipRef();
  if (!ref) return setStatus("Select a clip first.");
  try {
    pushUndoState();
    const { start, end } = getSelectionRange();
    const interStart = Math.max(start, ref.clip.startMs);
    const interEnd = Math.min(end, ref.clip.startMs + clipDurationMs(ref.clip));
    if (interEnd <= interStart) return setStatus("Selection does not overlap selected clip.");
    const localStart = interStart - ref.clip.startMs;
    const localEnd = interEnd - ref.clip.startMs;
    replaceClipWithCut(ref, localStart, localEnd, interStart, interEnd);
    markProjectDirty();
    refreshAll();
  } catch (err) {
    setStatus(String(err.message || err));
  }
}

function replaceClipWithCut(ref, localStart, localEnd, interStart, interEnd) {
  const srcBuffer = state.bufferMap.get(ref.clip.bufferId);
  const left = sliceBuffer(srcBuffer, 0, localStart);
  const right = sliceBuffer(srcBuffer, localEnd, clipDurationMs(ref.clip));
  ref.track.clips.splice(ref.clipIdx, 1);
  const inserts = [];
  if (left.duration > 0) {
    inserts.push({
      ...buildClip(ref.clip.name, registerBuffer(left), ref.clip.startMs, true),
      volumeDb: ref.clip.volumeDb || 0,
    });
  }
  if (right.duration > 0) {
    inserts.push({
      ...buildClip(ref.clip.name, registerBuffer(right), interEnd, true),
      volumeDb: ref.clip.volumeDb || 0,
    });
  }
  ref.track.clips.splice(ref.clipIdx, 0, ...inserts);
  pruneEmptyTracks(currentProject());
  state.selectedClip = -1;
}

function pasteClipboard() {
  const project = currentProject();
  if (!project || !state.clipboard) return setStatus("Clipboard empty.");
  pushUndoState();
  let target = state.selectedTrack;
  if (target < 0 || target >= project.tracks.length) target = project.tracks.length;
  while (project.tracks.length <= target) {
    project.tracks.push({ name: `Track ${project.tracks.length}`, muted: false, volumeDb: 0, isFinal: false, clips: [] });
  }
  const clip = buildClip(state.clipboard.name, state.clipboard.bufferId, state.currentPosMs, false);
  clip.volumeDb = state.clipboard.volumeDb || 0;
  project.tracks[target].clips.push(clip);
  state.selectedTrack = target;
  state.selectedClip = project.tracks[target].clips.length - 1;
  markProjectDirty();
  refreshAll();
}

function splitSelectedClip() {
  const ref = selectedClipRef();
  if (!ref) return setStatus("Select a clip first.");
  const splitAt = state.currentPosMs;
  const endMs = ref.clip.startMs + clipDurationMs(ref.clip);
  if (splitAt <= ref.clip.startMs || splitAt >= endMs) return setStatus("Playhead must be inside selected clip.");
  pushUndoState();
  const local = splitAt - ref.clip.startMs;
  const src = state.bufferMap.get(ref.clip.bufferId);
  const left = sliceBuffer(src, 0, local);
  const right = sliceBuffer(src, local, clipDurationMs(ref.clip));
  ref.track.clips.splice(ref.clipIdx, 1,
    { ...buildClip(ref.clip.name, registerBuffer(left), ref.clip.startMs, true), volumeDb: ref.clip.volumeDb || 0 },
    { ...buildClip(ref.clip.name, registerBuffer(right), splitAt, true), volumeDb: ref.clip.volumeDb || 0 },
  );
  markProjectDirty();
  refreshAll();
}

function reverseSelectedClip() {
  const ref = selectedClipRef();
  const project = currentProject();
  if (!ref || !project) return setStatus("Select a clip first.");
  pushUndoState();
  const src = state.bufferMap.get(ref.clip.bufferId);
  const reversed = reverseBuffer(src);
  const newTrackIdx = ref.trackIdx + 1;
  project.tracks.splice(newTrackIdx, 0, {
    name: `Track ${newTrackIdx + 1} Rev`,
    muted: false,
    volumeDb: 0,
    isFinal: false,
    clips: [{ ...buildClip(`${ref.clip.name} (rev)`, registerBuffer(reversed), ref.clip.startMs, ref.clip.spliced), volumeDb: ref.clip.volumeDb || 0 }],
  });
  renumberStandardTrackNames(project);
  markProjectDirty();
  refreshAll();
}

function renumberStandardTrackNames(project) {
  let n = 1;
  project.tracks.forEach((track) => {
    if (track.isFinal) {
      track.name = "Final Product";
      return;
    }
    if (track.name.includes("Rev")) return;
    track.name = `Track ${n}`;
    n += 1;
  });
}

function onTrackVolumeChanged() {
  const project = currentProject();
  if (!project) return;
  const value = Number(ui.trackVolSlider.value);
  ui.trackVolValue.textContent = `${value >= 0 ? "+" : ""}${value} dB`;
  if (state.selectedTrack < 0 || state.selectedTrack >= project.tracks.length) return;
  pushUndoState();
  project.tracks[state.selectedTrack].volumeDb = value;
  markProjectDirty();
  renderTimeline();
}

function onClipVolumeChanged() {
  const ref = selectedClipRef();
  const value = Number(ui.clipVolSlider.value);
  ui.clipVolValue.textContent = `${value >= 0 ? "+" : ""}${value} dB`;
  if (!ref) return;
  pushUndoState();
  ref.clip.volumeDb = value;
  markProjectDirty();
  renderTimeline();
}

function onZoomChanged() {
  state.pxPerSec = Number(ui.zoomInput.value);
  ui.zoomValue.textContent = `${state.pxPerSec}%`;
  renderTimeline();
}

function toggleSelectedTrackMute() {
  const project = currentProject();
  if (!project || state.selectedTrack < 0 || state.selectedTrack >= project.tracks.length) return setStatus("Select any clip in a row first.");
  pushUndoState();
  const track = project.tracks[state.selectedTrack];
  track.muted = !track.muted;
  markProjectDirty();
  setStatus(`${track.name} is now ${track.muted ? "muted" : "unmuted"}.`);
  renderTimeline();
}

function togglePlayPause() {
  const project = currentProject();
  if (!project) return;
  if (state.playback.isPlaying) pausePlayback();
  else startPlayback();
}

function getCurrentSpeed() {
  return Number(ui.speedSelect.value);
}

function dbToLinear(db) {
  return Math.pow(10, db / 20);
}

function startPlayback() {
  const project = currentProject();
  if (!project) return;
  const audioContext = getAudioContext();
  stopPlayback();
  const speed = getCurrentSpeed();
  const boostDb = Number(ui.boostSelect.value);
  const now = audioContext.currentTime + 0.03;
  const currentPos = state.currentPosMs;
  const fadeMs = Math.max(0, Number(ui.fadeInput.value || "0"));

  project.tracks.forEach((track) => {
    if (track.muted) return;
    track.clips.forEach((clip) => {
      const buffer = state.bufferMap.get(clip.bufferId);
      if (!buffer) return;
      const clipStart = clip.startMs;
      const clipEnd = clip.startMs + clipDurationMs(clip);
      if (clipEnd <= currentPos) return;
      const offsetMs = Math.max(0, currentPos - clipStart);
      const delayMs = Math.max(0, clipStart - currentPos);
      const availableMs = clipDurationMs(clip) - offsetMs;
      if (availableMs <= 0) return;

      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = speed;

      const gain = audioContext.createGain();
      const totalDb = (track.volumeDb || 0) + (clip.volumeDb || 0) + boostDb;
      gain.gain.value = dbToLinear(totalDb);

      source.connect(gain);
      gain.connect(audioContext.destination);

      if (ui.fadeCheckbox.checked && clip.spliced && fadeMs > 0) {
        const t0 = now + (delayMs / 1000);
        const fadeSec = Math.min(fadeMs / 1000, Math.max(0, availableMs / 2000));
        gain.gain.setValueAtTime(0.0001, t0);
        gain.gain.linearRampToValueAtTime(dbToLinear(totalDb), t0 + fadeSec);
      }

      source.start(now + delayMs / 1000, offsetMs / 1000, availableMs / 1000);
      state.playback.sources.push({ source, gain });
    });
  });

  state.playback.isPlaying = true;
  state.playback.startedAt = performance.now();
  state.playback.startPosMs = state.currentPosMs;
  state.playback.speed = speed;
  state.playback.stopAtMs = totalDurationMs();
  ui.playPauseBtn.textContent = "Pause";
  state.playback.timer = window.setInterval(updatePlaybackUi, 60);
  setStatus("Playing.");
}

function pausePlayback() {
  if (!state.playback.isPlaying) return;
  const elapsed = performance.now() - state.playback.startedAt;
  const advanced = elapsed * state.playback.speed;
  state.currentPosMs = Math.min(state.playback.startPosMs + advanced, state.playback.stopAtMs);
  stopPlayback(false);
  refreshPositionUi();
}

function stopAndRewind() {
  stopPlayback(false);
  state.currentPosMs = 0;
  state.playheadMs = 0;
  refreshPositionUi();
  renderTimeline();
}

function stopPlayback(resetStatus = false) {
  state.playback.sources.forEach((node) => {
    try { node.source.stop(); } catch (_err) {}
    try { node.source.disconnect(); } catch (_err) {}
    try { node.gain.disconnect(); } catch (_err) {}
  });
  state.playback.sources = [];
  state.playback.isPlaying = false;
  if (state.playback.timer) {
    clearInterval(state.playback.timer);
    state.playback.timer = null;
  }
  ui.playPauseBtn.textContent = "Play";
  if (resetStatus) setStatus("Stopped.");
}

function seekTo(ms) {
  state.currentPosMs = Math.max(0, Math.min(ms, totalDurationMs()));
  state.playheadMs = state.currentPosMs;
  refreshPositionUi();
  renderTimeline();
  if (state.playback.isPlaying) startPlayback();
}

function updatePlaybackUi() {
  if (!state.playback.isPlaying) return;
  const elapsed = performance.now() - state.playback.startedAt;
  const advanced = elapsed * state.playback.speed;
  state.currentPosMs = Math.min(state.playback.startPosMs + advanced, state.playback.stopAtMs);
  state.playheadMs = state.currentPosMs;
  refreshPositionUi();
  renderTimeline();
  if (state.currentPosMs >= state.playback.stopAtMs) stopPlayback();
}

async function exportMixWav() {
  const project = currentProject();
  if (!project) return;
  const totalMs = totalDurationMs();
  if (totalMs <= 0) return setStatus("Nothing to export.");

  const sampleRate = 44100;
  const frames = Math.max(1, Math.floor((totalMs / 1000) * sampleRate));
  const offline = new OfflineAudioContext(2, frames, sampleRate);
  const boostDb = Number(ui.boostSelect.value);

  project.tracks.forEach((track) => {
    if (track.muted) return;
    track.clips.forEach((clip) => {
      const buffer = state.bufferMap.get(clip.bufferId);
      if (!buffer) return;
      const src = offline.createBufferSource();
      src.buffer = buffer;
      src.playbackRate.value = getCurrentSpeed();
      const gain = offline.createGain();
      gain.gain.value = dbToLinear((track.volumeDb || 0) + (clip.volumeDb || 0) + boostDb);
      src.connect(gain);
      gain.connect(offline.destination);
      src.start(Math.max(0, clip.startMs / 1000));
    });
  });

  const rendered = await offline.startRendering();
  const wav = audioBufferToWav(rendered);
  const blob = new Blob([wav], { type: "audio/wav" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${project.name}_mix.wav`;
  a.click();
  URL.revokeObjectURL(url);
  setStatus("Export complete.");
}

function audioBufferToWav(buffer) {
  const channels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const length = buffer.length;
  const bytesPerSample = 2;
  const blockAlign = channels * bytesPerSample;
  const dataSize = length * blockAlign;
  const out = new ArrayBuffer(44 + dataSize);
  const view = new DataView(out);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  const channelData = [];
  for (let ch = 0; ch < channels; ch += 1) channelData.push(buffer.getChannelData(ch));
  for (let i = 0; i < length; i += 1) {
    for (let ch = 0; ch < channels; ch += 1) {
      const s = Math.max(-1, Math.min(1, channelData[ch][i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }
  return out;
}

function writeString(view, offset, value) {
  for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
}

function getAudioContext() {
  if (!state.audioContext) state.audioContext = new AudioContext();
  return state.audioContext;
}

function onTimelineMouseDown(e) {
  const project = currentProject();
  if (!project) return;
  const pos = timelinePos(e);
  const rowIdx = rowAtPos(pos.y);

  if (pos.x <= HEADER_W && rowIdx >= 0) {
    if (!project.tracks[rowIdx].isFinal) {
      pushUndoState();
      state.rowDrag = { rowIdx };
    } else {
      state.selectedTrack = rowIdx;
      state.selectedClip = -1;
      renderTimeline();
    }
    return;
  }

  const hit = clipAtPos(pos.x, pos.y);
  if (hit) {
    pushUndoState();
    state.selectedTrack = hit.trackIdx;
    state.selectedClip = hit.clipIdx;
    const clip = project.tracks[hit.trackIdx].clips[hit.clipIdx];
    state.drag = {
      trackIdx: hit.trackIdx,
      clipIdx: hit.clipIdx,
      offsetMs: Math.max(0, xToMs(pos.x) - clip.startMs),
    };
    onTimelineSelection();
    renderTimeline();
    return;
  }

  state.playheadMs = xToMs(pos.x);
  state.currentPosMs = state.playheadMs;
  refreshPositionUi();
  renderTimeline();
}

function onTimelineMouseMove(e) {
  const project = currentProject();
  if (!project) return;
  const pos = timelinePos(e);
  autoScrollOnDrag(e.clientX);

  if (state.rowDrag) {
    let target = rowAtPos(pos.y);
    if (target === 0) target = 1;
    if (target >= 1 && target !== state.rowDrag.rowIdx) {
      const moved = project.tracks.splice(state.rowDrag.rowIdx, 1)[0];
      project.tracks.splice(target, 0, moved);
      state.rowDrag.rowIdx = target;
      state.selectedTrack = target;
      state.selectedClip = -1;
      markProjectDirty();
      renderTimeline();
    }
    return;
  }

  if (!state.drag) return;

  let targetTrack = rowAtPos(pos.y);
  if (targetTrack >= 0 && targetTrack !== state.drag.trackIdx) moveDraggedClipToTrack(targetTrack);

  const dragTrack = project.tracks[state.drag.trackIdx];
  if (!dragTrack || state.drag.clipIdx >= dragTrack.clips.length) return;
  const clip = dragTrack.clips[state.drag.clipIdx];
  let desired = Math.max(0, xToMs(pos.x) - state.drag.offsetMs);

  if (!e.ctrlKey) {
    let nearest = null;
    dragTrack.clips.forEach((other, idx) => {
      if (idx === state.drag.clipIdx) return;
      const end = other.startMs + clipDurationMs(other);
      if (end <= desired && (nearest === null || end > nearest)) nearest = end;
    });
    if (nearest !== null && Math.abs(desired - nearest) <= SNAP_MS) desired = nearest;
  }

  clip.startMs = desired;
  state.playheadMs = desired;
  state.currentPosMs = desired;
  if (pruneEmptyTracks(project)) resolveSelectionAfterPrune();
  markProjectDirty();
  refreshPositionUi();
  renderTimeline();
}

function onTimelineMouseUp() {
  state.drag = null;
  state.rowDrag = null;
}

function moveDraggedClipToTrack(targetTrack) {
  const project = currentProject();
  const sourceTrack = project.tracks[state.drag.trackIdx];
  if (!sourceTrack) return;
  const clip = sourceTrack.clips.splice(state.drag.clipIdx, 1)[0];
  if (!clip) return;
  project.tracks[targetTrack].clips.push(clip);

  const removedSource = sourceTrack.clips.length === 0 && !sourceTrack.isFinal;
  if (removedSource) {
    project.tracks.splice(state.drag.trackIdx, 1);
    if (targetTrack > state.drag.trackIdx) targetTrack -= 1;
  }
  state.drag.trackIdx = targetTrack;
  state.drag.clipIdx = project.tracks[targetTrack].clips.length - 1;
  state.selectedTrack = state.drag.trackIdx;
  state.selectedClip = state.drag.clipIdx;
}

function resolveSelectionAfterPrune() {
  const project = currentProject();
  if (!project) return;
  if (state.selectedTrack >= project.tracks.length) {
    state.selectedTrack = -1;
    state.selectedClip = -1;
  }
}

function autoScrollOnDrag(clientX) {
  const rect = ui.timelineScroll.getBoundingClientRect();
  const edge = 44;
  const step = Math.max(12, Math.floor(rect.width * 0.06));
  if (clientX - rect.left < edge) ui.timelineScroll.scrollLeft -= step;
  else if (rect.right - clientX < edge) ui.timelineScroll.scrollLeft += step;
}

function timelinePos(e) {
  const rect = ui.timelineCanvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function rowTop(trackIdx) {
  if (trackIdx === 0) return TOP_MARGIN + FINAL_ROW_PAD;
  return TOP_MARGIN + FINAL_CONTAINER_H + SECTION_GAP + (trackIdx - 1) * ROW_H;
}

function rowAtPos(y) {
  const project = currentProject();
  if (!project) return -1;
  for (let i = 0; i < project.tracks.length; i += 1) {
    const top = rowTop(i);
    if (y >= top && y <= top + ROW_H) return i;
  }
  return -1;
}

function clipAtPos(x, y) {
  const project = currentProject();
  if (!project) return null;
  for (let t = 0; t < project.tracks.length; t += 1) {
    const top = rowTop(t);
    for (let c = 0; c < project.tracks[t].clips.length; c += 1) {
      const clip = project.tracks[t].clips[c];
      const x1 = msToX(clip.startMs);
      const x2 = msToX(clip.startMs + clipDurationMs(clip));
      const rect = { x: x1, y: top + (ROW_H - CLIP_H) / 2, w: Math.max(10, x2 - x1), h: CLIP_H };
      if (x >= rect.x && x <= rect.x + rect.w && y >= rect.y && y <= rect.y + rect.h) return { trackIdx: t, clipIdx: c };
    }
  }
  return null;
}

function msToX(ms) {
  return HEADER_W + Math.floor(ms * (state.pxPerSec / 1000));
}

function xToMs(x) {
  return Math.floor(Math.max(0, x - HEADER_W) / (state.pxPerSec / 1000));
}

function onTimelineSelection() {
  const ref = selectedClipRef();
  if (!ref) return;
  ui.startInput.value = formatSeconds(ref.clip.startMs);
  ui.endInput.value = formatSeconds(ref.clip.startMs + clipDurationMs(ref.clip));
  refreshTrackVolumeUi();
  refreshClipVolumeUi();
}

function refreshTrackVolumeUi() {
  const project = currentProject();
  if (!project || state.selectedTrack < 0 || state.selectedTrack >= project.tracks.length) {
    ui.trackVolSlider.value = "0";
    ui.trackVolValue.textContent = "+0 dB";
    return;
  }
  const value = Number(project.tracks[state.selectedTrack].volumeDb || 0);
  ui.trackVolSlider.value = String(value);
  ui.trackVolValue.textContent = `${value >= 0 ? "+" : ""}${value} dB`;
}

function refreshClipVolumeUi() {
  const ref = selectedClipRef();
  if (!ref) {
    ui.clipVolSlider.value = "0";
    ui.clipVolValue.textContent = "+0 dB";
    return;
  }
  const value = Number(ref.clip.volumeDb || 0);
  ui.clipVolSlider.value = String(value);
  ui.clipVolValue.textContent = `${value >= 0 ? "+" : ""}${value} dB`;
}

function refreshPositionUi() {
  const total = totalDurationMs();
  ui.seekSlider.max = String(Math.max(0, total));
  ui.seekSlider.value = String(Math.max(0, Math.min(total, Math.floor(state.currentPosMs))));
  ui.positionLabel.textContent = `${formatSeconds(state.currentPosMs)} s`;
  ui.durationLabel.textContent = `${formatSeconds(total)} s`;
}

function refreshAll() {
  pruneEmptyTracks(currentProject());
  ensureFinalTrack(currentProject());
  refreshProjectSelect();
  refreshPositionUi();
  refreshTrackVolumeUi();
  refreshClipVolumeUi();
  renderTimeline();
}

function renderTimeline() {
  const project = currentProject();
  const ctx = ui.ctx;
  const totalMs = totalDurationMs();
  const width = Math.max(ui.timelineScroll.clientWidth, HEADER_W + Math.floor(totalMs * (state.pxPerSec / 1000)) + 320);
  const nonFinal = Math.max(0, (project?.tracks.length || 1) - 1);
  const height = Math.max(220, TOP_MARGIN + FINAL_CONTAINER_H + SECTION_GAP + nonFinal * ROW_H + 20);

  ui.timelineCanvas.width = width;
  ui.timelineCanvas.height = height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(0, 0, width, height);

  if (!project) {
    ctx.fillStyle = "#fff";
    ctx.fillText("Create a project, then add audio clips.", 24, 42);
    return;
  }

  ctx.fillStyle = "#121f35";
  ctx.fillRect(0, TOP_MARGIN, width, FINAL_CONTAINER_H);
  ctx.strokeStyle = "#3c537b";
  ctx.strokeRect(0.5, TOP_MARGIN + 0.5, width - 1, FINAL_CONTAINER_H - 1);
  ctx.fillStyle = "#d9e6ff";
  ctx.font = "600 12px Segoe UI";
  ctx.fillText("Final Mix", 14, TOP_MARGIN + 14);

  project.tracks.forEach((track, tIdx) => {
    const top = rowTop(tIdx);
    ctx.fillStyle = track.isFinal ? "#1a2337" : (tIdx % 2 === 0 ? "#111a2b" : "#0f1726");
    if (track.muted) ctx.fillStyle = tIdx % 2 === 0 ? "#0c1018" : "#0b0f16";
    ctx.fillRect(0, top, width, ROW_H);

    ctx.fillStyle = track.isFinal ? "#ffecc4" : (track.muted ? "#98a6ba" : "#f4efe2");
    ctx.font = "700 13px Segoe UI";
    const label = track.muted ? `${track.name} [MUTED]` : track.name;
    ctx.fillText(label, 10, top + 33);

    track.clips.forEach((clip, cIdx) => {
      const x1 = msToX(clip.startMs);
      const x2 = msToX(clip.startMs + clipDurationMs(clip));
      const w = Math.max(10, x2 - x1);
      const y = top + (ROW_H - CLIP_H) / 2;
      const selected = tIdx === state.selectedTrack && cIdx === state.selectedClip;
      ctx.fillStyle = track.muted ? "#4f5866" : (selected ? "#d18d53" : (clip.spliced ? "#c9a96a" : "#be7b46"));
      ctx.strokeStyle = "#f4efe2";
      roundedRect(ctx, x1, y, w, CLIP_H, 4);
      ctx.fill();
      ctx.stroke();

      drawWaveform(ctx, clip.waveform, x1 + 3, y + 3, w - 6, CLIP_H - 6, track.muted);

      ctx.fillStyle = "#f7f7f7";
      ctx.font = "600 11px Segoe UI";
      ctx.fillText(`${formatSeconds(clipDurationMs(clip))}s`, x1 + w - 44, y + 21);
    });
  });

  const secTotal = Math.floor(totalMs / 1000) + 8;
  for (let sec = 0; sec < secTotal; sec += 1) {
    const x = msToX(sec * 1000);
    ctx.strokeStyle = "#24334e";
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.fillStyle = "#8ea0bf";
    ctx.font = "500 11px Segoe UI";
    ctx.fillText(String(sec), x + 2, 12);
  }

  const playX = msToX(state.playheadMs);
  ctx.strokeStyle = "#ffecc4";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(playX, 0);
  ctx.lineTo(playX, height);
  ctx.stroke();
  ctx.lineWidth = 1;
}

function drawWaveform(ctx, wave, x, y, w, h, muted) {
  if (!wave || wave.length < 2 || w < 2) return;
  const mid = y + h / 2;
  ctx.strokeStyle = muted ? "#b0b8c5" : "#e8efe9";
  ctx.beginPath();
  for (let px = 0; px < w; px += 1) {
    const idx = Math.floor((px / Math.max(1, w - 1)) * (wave.length - 1));
    const amp = Math.max(0, Math.min(1, wave[idx]));
    const half = Math.floor(((h - 6) * amp) / 2);
    const xx = x + px;
    ctx.moveTo(xx, mid - half);
    ctx.lineTo(xx, mid + half);
  }
  ctx.stroke();
}

function roundedRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function setStatus(text) {
  ui.statusLabel.textContent = text;
}

function markProjectDirty(autosave = true) {
  const project = currentProject();
  if (!project) return;
  project.revision += 1;
  if (autosave) scheduleAutosave();
}

function scheduleAutosave() {
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = setTimeout(() => {
    saveAutosave().catch(() => {});
  }, 350);
}

async function saveAutosave() {
  const payload = {
    currentProjectName: state.currentProjectName,
    nextBufferId: state.nextBufferId,
    nextClipId: state.nextClipId,
    projects: projectSnapshotPack(),
    buffers: [],
  };
  for (const [id, buffer] of state.bufferMap.entries()) {
    const wav = audioBufferToWav(buffer);
    const base64 = arrayBufferToBase64(wav);
    payload.buffers.push({ id, wavBase64: base64 });
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function projectSnapshotPack() {
  const out = {};
  Object.entries(state.projects).forEach(([name, proj]) => {
    out[name] = projectSnapshot(proj);
    out[name].undo = proj.undo || [];
    out[name].redo = proj.redo || [];
  });
  return out;
}

function loadAutosave() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw);
    state.loading = true;
    state.projects = parsed.projects || {};
    Object.values(state.projects).forEach((project) => {
      project.undo = project.undo || [];
      project.redo = project.redo || [];
      ensureFinalTrack(project);
    });
    state.currentProjectName = parsed.currentProjectName || Object.keys(state.projects)[0] || null;
    state.nextBufferId = Number(parsed.nextBufferId || 1);
    state.nextClipId = Number(parsed.nextClipId || 1);
    const audioContext = getAudioContext();
    const jobs = (parsed.buffers || []).map(async (item) => {
      const arr = base64ToArrayBuffer(item.wavBase64);
      const buffer = await audioContext.decodeAudioData(arr.slice(0));
      state.bufferMap.set(Number(item.id), buffer);
    });
    Promise.all(jobs).catch(() => {});
  } catch (_err) {
    setStatus("Autosave load failed.");
  } finally {
    state.loading = false;
  }
}

function arrayBufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

async function onSaveProjectAs() {
  const project = currentProject();
  if (!project) return;
  const payload = {
    format: "kimix-web-project-v1",
    project: projectSnapshot(project),
    buffers: [],
    nextBufferId: state.nextBufferId,
    nextClipId: state.nextClipId,
  };
  const usedBufferIds = new Set();
  project.tracks.forEach((t) => t.clips.forEach((c) => usedBufferIds.add(c.bufferId)));
  for (const id of usedBufferIds) {
    const buffer = state.bufferMap.get(id);
    if (!buffer) continue;
    payload.buffers.push({ id, wavBase64: arrayBufferToBase64(audioBufferToWav(buffer)) });
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${project.name}.kimixweb.json`;
  a.click();
  URL.revokeObjectURL(url);
  setStatus("Project exported.");
}

async function onOpenProjectFile(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    if (parsed.format !== "kimix-web-project-v1" || !parsed.project) throw new Error("Unsupported project file format.");
    const name = uniqueProjectName(parsed.project.name || "Imported Project");
    const audioContext = getAudioContext();

    const loadedIds = new Map();
    for (const row of parsed.buffers || []) {
      const buffer = await audioContext.decodeAudioData(base64ToArrayBuffer(row.wavBase64).slice(0));
      const newId = registerBuffer(buffer);
      loadedIds.set(Number(row.id), newId);
    }

    const proj = parsed.project;
    proj.name = name;
    proj.undo = [];
    proj.redo = [];
    proj.tracks.forEach((track) => {
      track.clips.forEach((clip) => {
        clip.bufferId = loadedIds.get(clip.bufferId);
      });
    });
    ensureFinalTrack(proj);
    state.projects[name] = proj;
    state.currentProjectName = name;
    state.nextClipId = Math.max(state.nextClipId, Number(parsed.nextClipId || state.nextClipId));
    refreshProjectSelect();
    switchProject(name);
    scheduleAutosave();
    setStatus(`Opened project: ${name}`);
  } catch (err) {
    setStatus(String(err.message || err));
  } finally {
    e.target.value = "";
  }
}

function sliceBuffer(source, startMs, endMs) {
  const start = Math.max(0, Math.floor((startMs / 1000) * source.sampleRate));
  const end = Math.max(start, Math.floor((endMs / 1000) * source.sampleRate));
  const len = Math.max(1, end - start);
  const out = new AudioBuffer({ numberOfChannels: source.numberOfChannels, length: len, sampleRate: source.sampleRate });
  for (let ch = 0; ch < source.numberOfChannels; ch += 1) {
    out.copyToChannel(source.getChannelData(ch).slice(start, end), ch, 0);
  }
  return out;
}

function reverseBuffer(source) {
  const out = new AudioBuffer({ numberOfChannels: source.numberOfChannels, length: source.length, sampleRate: source.sampleRate });
  for (let ch = 0; ch < source.numberOfChannels; ch += 1) {
    const data = source.getChannelData(ch);
    const rev = new Float32Array(data.length);
    for (let i = 0; i < data.length; i += 1) rev[i] = data[data.length - 1 - i];
    out.copyToChannel(rev, ch, 0);
  }
  return out;
}
