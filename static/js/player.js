// Video player: continue where the user stopped, and save progress while watching.
document.addEventListener("DOMContentLoaded", () => {
  const video = document.querySelector("video.player[data-progress-url]");
  if (!video) return;

  const url = video.dataset.progressUrl;
  const token = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const start = Number(video.dataset.position || 0);
  let lastSaved = 0;

  const save = () => {
    if (!video.duration || !isFinite(video.duration)) return;
    lastSaved = video.currentTime;
    const body = new URLSearchParams({ position: video.currentTime, duration: video.duration });
    // keepalive: the request still goes through if the user closes the page right away
    fetch(url, { method: "POST", headers: { "X-CSRFToken": token }, body, keepalive: true }).catch(() => {});
  };

  video.addEventListener("loadedmetadata", () => {
    // Don't jump to the very end of an already finished video
    if (start > 0 && start < video.duration - 5) video.currentTime = start;
  });

  video.addEventListener("timeupdate", () => {
    if (Math.abs(video.currentTime - lastSaved) >= 10) save();  // at most one request per 10 seconds
  });

  ["pause", "ended"].forEach((event) => video.addEventListener(event, save));
  document.addEventListener("visibilitychange", () => { if (document.hidden) save(); });
});