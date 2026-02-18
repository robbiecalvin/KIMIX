const HEADER_W = 220;
const ROW_H = 54;
const CLIP_H = 34;
const TOP_MARGIN = 10;
const FINAL_CONTAINER_H = 78;
const FINAL_ROW_TOP_PAD = 12;
const SECTION_GAP = 10;
const SNAP_MS = 250;

let pxPerSec = 100;
let clipId = 1;
let trackId = 1;

const state = {
  project: createProject("Web Project"),
  selected: { trackIdx: -1, clipIdx: -1 },
  playheadMs: 0,
  drag: null,
  audioCtx: null,
  playingNodes: [],
};

const canvas = document.getElementById("timeline-canvas");
const ctx = canvas.getContext("2d");
const scroller = document.getElementById("timeline-scroll");
const statusText = document.getElementById("status-text");
const zoomInput = document.getElementById("zoom-input");
const zoomValue = document.getElementById("zoom-value");

init();

function init() {
  wireModes();
  wireEditorActions();
  ensureFinalTrack(state.project);
  render();
}

function wireModes() {
  const modeButtons = [...document.querySelectorAll(".mode-btn")];
  const panels = {
    now: document.getElementById("now-panel"),
    playlist: document.getElementById("playlist-panel"),
    editor: document.getElementById("editor-panel"),
  };

  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      modeButtons.forEach((b) => b.classList.toggle("active", b === btn));
      Object.entries(panels).forEach(([key, panel]) => panel.classList.toggle("active", key === btn.dataset.mode));
    });
  });
}

function wireEditorActions() {
  document.getElementById("new-project-btn").addEventListener("click", () => {
    state.project = createProject(`Web Project ${Date.now().toString().slice(-4)}`);
    state.selected = { trackIdx: -1, clipIdx: -1 };
    state.playheadMs = 0;
    stopMix();
    render();
    setStatus("New project created.");
  });

  document.getElementById("audio-input").addEventListener("change", onImportAudio);
  document.getElementById("play-btn").addEventListener("click", playMix);
  document.getElementById("stop-btn").addEventListener("click", stopMix);
  zoomInput.addEventListener("input", () => {
    pxPerSec = Number(zoomInput.value);
    zoomValue.textContent = `${pxPerSec}%`;
    render();
  });

  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);
}

function createProject(name) {
  return {
    name,
    tracks: [
      {
        id: trackId++,
        name: "Final Product",
        isFinal: true,
        muted: false,
        clips: [],
      },
    ],
  };
}

function ensureFinalTrack(project) {
  let idx = project.tracks.findIndex((t) => t.isFinal || t.name.toLowerCase() === "final product");
  if (idx < 0) {
    project.tracks.unshift({
      id: trackId++,
      name: "Final Product",
      isFinal: true,
      muted: false,
      clips: [],
    });
  } else if (idx !== 0) {
    const [finalTrack] = project.tracks.splice(idx, 1);
    finalTrack.isFinal = true;
    finalTrack.name = "Final Product";
    project.tracks.unshift(finalTrack);
  } else {
    project.tracks[0].isFinal = true;
    project.tracks[0].name = "Final Product";
  }

  for (let i = 1; i < project.tracks.length; i += 1) {
    project.tracks[i].isFinal = false;
  }
}

function pruneEmptyTracks(project) {
  const next = [project.tracks[0], ...project.tracks.slice(1).filter((t) => t.clips.length > 0)];
  project.tracks = next;
  ensureFinalTrack(project);
}

function totalDurationMs() {
  let maxMs = 0;
  state.project.tracks.forEach((track) => {
    track.clips.forEach((clip) => {
      maxMs = Math.max(maxMs, clip.startMs + clip.durationMs);
    });
  });
  return maxMs;
}

function rowTopForTrack(trackIdx) {
  if (trackIdx === 0) return TOP_MARGIN + FINAL_ROW_TOP_PAD;
  return TOP_MARGIN + FINAL_CONTAINER_H + SECTION_GAP + (trackIdx - 1) * ROW_H;
}

function trackAtY(y) {
  for (let i = 0; i < state.project.tracks.length; i += 1) {
    const top = rowTopForTrack(i);
    if (y >= top && y <= top + ROW_H) return i;
  }
  return -1;
}

function msToX(ms) {
  return HEADER_W + (ms * (pxPerSec / 1000));
}

function xToMs(x) {
  const px = Math.max(0, x - HEADER_W);
  return Math.floor(px / (pxPerSec / 1000));
}

function clipAtPos(x, y) {
  for (let t = 0; t < state.project.tracks.length; t += 1) {
    const track = state.project.tracks[t];
    const rowTop = rowTopForTrack(t);
    for (let c = 0; c < track.clips.length; c += 1) {
      const clip = track.clips[c];
      const x1 = msToX(clip.startMs);
      const x2 = msToX(clip.startMs + clip.durationMs);
      const w = Math.max(10, x2 - x1);
      const y1 = rowTop + (ROW_H - CLIP_H) / 2;
      if (x >= x1 && x <= x1 + w && y >= y1 && y <= y1 + CLIP_H) {
        return { trackIdx: t, clipIdx: c };
      }
    }
  }
  return null;
}

async function onImportAudio(event) {
  const files = [...(event.target.files || [])];
  if (!files.length) return;
  ensureFinalTrack(state.project);
  const audioCtx = getAudioContext();

  for (const file of files) {
    try {
      const arr = await file.arrayBuffer();
      const buffer = await audioCtx.decodeAudioData(arr.slice(0));
      state.project.tracks.push({
        id: trackId++,
        name: `Track ${state.project.tracks.length}`,
        isFinal: false,
        muted: false,
        clips: [{
          id: clipId++,
          name: file.name,
          startMs: 0,
          durationMs: Math.floor(buffer.duration * 1000),
          audioBuffer: buffer,
          waveform: makeWaveform(buffer, 180),
        }],
      });
    } catch (_err) {
      setStatus(`Failed to import ${file.name}.`);
    }
  }

  event.target.value = "";
  render();
  setStatus("Import complete. Drag clips into Final Product.");
}

function makeWaveform(audioBuffer, bins) {
  const channel = audioBuffer.getChannelData(0);
  const block = Math.max(1, Math.floor(channel.length / bins));
  const values = [];
  for (let i = 0; i < bins; i += 1) {
    const start = i * block;
    const end = Math.min(channel.length, start + block);
    let peak = 0;
    for (let j = start; j < end; j += 1) {
      const v = Math.abs(channel[j]);
      if (v > peak) peak = v;
    }
    values.push(Math.min(1, peak));
  }
  return values;
}

function onMouseDown(e) {
  const { offsetX: x, offsetY: y } = e;
  const hit = clipAtPos(x, y);
  if (!hit) {
    state.playheadMs = xToMs(x);
    render();
    return;
  }

  const clip = state.project.tracks[hit.trackIdx].clips[hit.clipIdx];
  state.selected = { trackIdx: hit.trackIdx, clipIdx: hit.clipIdx };
  state.drag = {
    trackIdx: hit.trackIdx,
    clipIdx: hit.clipIdx,
    offsetMs: Math.max(0, xToMs(x) - clip.startMs),
  };
  render();
}

function onMouseMove(e) {
  if (!state.drag) return;
  autoScrollWhileDragging(e.clientX);

  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;

  const targetTrackIdx = trackAtY(y);
  if (targetTrackIdx >= 0 && targetTrackIdx !== state.drag.trackIdx) {
    moveDraggingClipToTrack(targetTrackIdx);
  }

  const dragTrack = state.project.tracks[state.drag.trackIdx];
  const clip = dragTrack?.clips[state.drag.clipIdx];
  if (!clip) return;

  let desired = Math.max(0, xToMs(x) - state.drag.offsetMs);
  if (!e.ctrlKey) {
    let nearestLeftEnd = null;
    dragTrack.clips.forEach((other, i) => {
      if (i === state.drag.clipIdx) return;
      const end = other.startMs + other.durationMs;
      if (end <= desired && (nearestLeftEnd === null || end > nearestLeftEnd)) nearestLeftEnd = end;
    });
    if (nearestLeftEnd !== null && Math.abs(desired - nearestLeftEnd) <= SNAP_MS) desired = nearestLeftEnd;
  }

  clip.startMs = desired;
  state.playheadMs = desired;
  pruneEmptyTracks(state.project);
  render();
}

function onMouseUp() {
  state.drag = null;
}

function moveDraggingClipToTrack(targetTrackIdx) {
  const fromTrack = state.project.tracks[state.drag.trackIdx];
  const toTrack = state.project.tracks[targetTrackIdx];
  const clip = fromTrack.clips.splice(state.drag.clipIdx, 1)[0];
  if (!clip) return;
  toTrack.clips.push(clip);

  const fromIdxBeforePrune = state.drag.trackIdx;
  pruneEmptyTracks(state.project);

  let resolvedTarget = targetTrackIdx;
  if (targetTrackIdx > fromIdxBeforePrune && fromTrack.clips.length === 0 && !fromTrack.isFinal) {
    resolvedTarget -= 1;
  }
  state.drag.trackIdx = resolvedTarget;
  state.drag.clipIdx = state.project.tracks[resolvedTarget].clips.length - 1;
  state.selected = { trackIdx: state.drag.trackIdx, clipIdx: state.drag.clipIdx };
}

function autoScrollWhileDragging(clientX) {
  const rect = scroller.getBoundingClientRect();
  const edge = 44;
  const step = Math.max(12, Math.floor(rect.width * 0.06));
  if (clientX - rect.left < edge) {
    scroller.scrollLeft -= step;
  } else if (rect.right - clientX < edge) {
    scroller.scrollLeft += step;
  }
}

function getAudioContext() {
  if (!state.audioCtx) {
    state.audioCtx = new window.AudioContext();
  }
  return state.audioCtx;
}

function playMix() {
  stopMix();
  const audioCtx = getAudioContext();
  const now = audioCtx.currentTime + 0.03;

  state.project.tracks.forEach((track) => {
    if (track.muted) return;
    track.clips.forEach((clip) => {
      if (!clip.audioBuffer) return;
      const source = audioCtx.createBufferSource();
      source.buffer = clip.audioBuffer;
      source.connect(audioCtx.destination);
      source.start(now + (clip.startMs / 1000));
      state.playingNodes.push(source);
    });
  });

  setStatus("Playing mix.");
}

function stopMix() {
  state.playingNodes.forEach((node) => {
    try { node.stop(); } catch (_err) {}
    try { node.disconnect(); } catch (_err) {}
  });
  state.playingNodes = [];
  setStatus("Stopped.");
}

function setStatus(text) {
  statusText.textContent = text;
}

function render() {
  ensureFinalTrack(state.project);
  const totalMs = totalDurationMs();
  const width = Math.max(scroller.clientWidth, HEADER_W + Math.floor(totalMs * (pxPerSec / 1000)) + 320);
  const nonFinalRows = Math.max(0, state.project.tracks.length - 1);
  const height = Math.max(220, TOP_MARGIN + FINAL_CONTAINER_H + SECTION_GAP + (nonFinalRows * ROW_H) + 20);
  canvas.width = width;
  canvas.height = height;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "#121f35";
  ctx.fillRect(0, TOP_MARGIN, width, FINAL_CONTAINER_H);
  ctx.strokeStyle = "#3c537b";
  ctx.strokeRect(0.5, TOP_MARGIN + 0.5, width - 1, FINAL_CONTAINER_H - 1);
  ctx.fillStyle = "#d9e6ff";
  ctx.font = "600 12px Avenir Next";
  ctx.fillText("Final Mix", 14, TOP_MARGIN + 14);

  state.project.tracks.forEach((track, tIdx) => {
    const rowTop = rowTopForTrack(tIdx);
    ctx.fillStyle = track.isFinal ? "#1a2337" : (tIdx % 2 === 0 ? "#111a2b" : "#0f1726");
    ctx.fillRect(0, rowTop, width, ROW_H);

    ctx.fillStyle = track.isFinal ? "#ffecc4" : "#f4efe2";
    ctx.font = "700 13px Avenir Next";
    ctx.fillText(track.name, 12, rowTop + 32);

    track.clips.forEach((clip, cIdx) => {
      const x1 = msToX(clip.startMs);
      const x2 = msToX(clip.startMs + clip.durationMs);
      const w = Math.max(10, x2 - x1);
      const y = rowTop + (ROW_H - CLIP_H) / 2;
      const selected = tIdx === state.selected.trackIdx && cIdx === state.selected.clipIdx;

      ctx.fillStyle = selected ? "#d18d53" : "#be7b46";
      ctx.strokeStyle = "#f4efe2";
      roundRect(ctx, x1, y, w, CLIP_H, 4);
      ctx.fill();
      ctx.stroke();

      drawWaveform(clip, x1 + 3, y + 3, w - 6, CLIP_H - 6);
      ctx.fillStyle = "#f7f7f7";
      ctx.font = "600 11px Avenir Next";
      const dur = (clip.durationMs / 1000).toFixed(2);
      ctx.fillText(dur + "s", x1 + w - 40, y + 21);
    });
  });

  const secCount = Math.floor(totalMs / 1000) + 8;
  for (let s = 0; s < secCount; s += 1) {
    const x = msToX(s * 1000);
    ctx.strokeStyle = "#24334e";
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.fillStyle = "#8ea0bf";
    ctx.font = "500 11px Avenir Next";
    ctx.fillText(String(s), x + 2, 12);
  }

  const pxPlayhead = msToX(state.playheadMs);
  ctx.strokeStyle = "#ffecc4";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pxPlayhead, 0);
  ctx.lineTo(pxPlayhead, height);
  ctx.stroke();
  ctx.lineWidth = 1;
}

function drawWaveform(clip, x, y, w, h) {
  if (!clip.waveform || clip.waveform.length < 2 || w < 2) return;
  const mid = y + h / 2;
  ctx.strokeStyle = "#e8efe9";
  ctx.beginPath();
  for (let px = 0; px < w; px += 1) {
    const idx = Math.floor((px / Math.max(1, w - 1)) * (clip.waveform.length - 1));
    const amp = Math.max(0, Math.min(1, clip.waveform[idx]));
    const half = ((h - 4) * amp) / 2;
    const xPos = x + px;
    ctx.moveTo(xPos, mid - half);
    ctx.lineTo(xPos, mid + half);
  }
  ctx.stroke();
}

function roundRect(context, x, y, w, h, r) {
  context.beginPath();
  context.moveTo(x + r, y);
  context.arcTo(x + w, y, x + w, y + h, r);
  context.arcTo(x + w, y + h, x, y + h, r);
  context.arcTo(x, y + h, x, y, r);
  context.arcTo(x, y, x + w, y, r);
  context.closePath();
}
