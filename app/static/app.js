// CineTracks Frontend Application Logic

let currentSearchResults = [];
let currentlyPlayingTrackId = null;
let downloadPollInterval = null;

const audioPlayer = document.getElementById("globalAudioPlayer");
const movieInput = document.getElementById("movieInput");
const searchBtn = document.getElementById("searchBtn");
const loadingSection = document.getElementById("loadingSection");
const resultsSection = document.getElementById("resultsSection");
const movieCardsContainer = document.getElementById("movieCardsContainer");
const totalTracksCount = document.getElementById("totalTracksCount");
const summaryText = document.getElementById("summaryText");

// Sample buttons
document.getElementById("sampleHollywoodBtn").addEventListener("click", () => {
  movieInput.value = "Inception\nInterstellar\nLa La Land";
});

document.getElementById("sampleIndianBtn").addEventListener("click", () => {
  movieInput.value = "Roja\nLeo\nRRR";
});

document.getElementById("sampleMixBtn").addEventListener("click", () => {
  movieInput.value = "Inception\nRoja\nGladiator\nDil Se";
});

document.getElementById("clearInputBtn").addEventListener("click", () => {
  movieInput.value = "";
  movieInput.focus();
});

// Keyboard shortcut: Ctrl + Enter / Cmd + Enter
movieInput.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    handleSearch();
  }
});

searchBtn.addEventListener("click", handleSearch);

async function handleSearch() {
  const text = movieInput.value.trim();
  if (!text) {
    alert("Please enter at least one movie name.");
    movieInput.focus();
    return;
  }

  const movies = text.split("\n").map(m => m.trim()).filter(m => m.length > 0);
  if (movies.length === 0) return;

  // Show loading
  loadingSection.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  searchBtn.disabled = true;
  searchBtn.classList.add("opacity-50", "cursor-not-allowed");

  // Stop any active audio preview
  stopAudio();

  const languageSelect = document.getElementById("movieLanguageSelect");
  const language = languageSelect ? languageSelect.value : "all";

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ movies, language })
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Search failed");
    }

    const data = await response.json();
    currentSearchResults = data.results || [];
    renderResults(currentSearchResults, data.total_tracks);

  } catch (error) {
    alert(`Error searching soundtracks: ${error.message}`);
  } finally {
    loadingSection.classList.add("hidden");
    searchBtn.disabled = false;
    searchBtn.classList.remove("opacity-50", "cursor-not-allowed");
    lucide.createIcons();
  }
}

function renderResults(results, totalTracks) {
  movieCardsContainer.innerHTML = "";
  totalTracksCount.innerText = totalTracks;
  summaryText.innerText = `${totalTracks} songs found across ${results.length} movie${results.length === 1 ? '' : 's'}`;

  results.forEach((movie, movieIndex) => {
    const card = document.createElement("div");
    card.className = "bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg transition-all hover:border-slate-700";

    if (!movie.found || !movie.tracks || movie.tracks.length === 0) {
      // Not found card
      card.innerHTML = `
        <div class="p-5 flex items-center justify-between border-l-4 border-amber-500 bg-amber-950/20">
          <div class="flex items-center space-x-3">
            <div class="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0">
              <i data-lucide="help-circle" class="w-5 h-5"></i>
            </div>
            <div>
              <h4 class="text-sm font-bold text-white">${escapeHtml(movie.movie_query)}</h4>
              <p class="text-xs text-amber-300/80">${escapeHtml(movie.error || 'No soundtrack album found. Try checking the movie name spelling.')}</p>
            </div>
          </div>
          <span class="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-400 font-medium border border-amber-500/20">
            0 tracks
          </span>
        </div>
      `;
      movieCardsContainer.appendChild(card);
      return;
    }

    const artwork = movie.artwork_url || "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=300&q=80";

    card.innerHTML = `
      <!-- Movie Header -->
      <div class="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800/80 bg-slate-900/50">
        <div class="flex items-center space-x-4">
          <img src="${artwork}" alt="${escapeHtml(movie.album_title || movie.movie_query)}" class="w-16 h-16 rounded-xl object-cover shadow-md border border-slate-700/60 shrink-0">
          <div>
            <div class="flex items-center gap-2">
              <h4 class="text-base font-bold text-white">${escapeHtml(movie.movie_query)}</h4>
              ${movie.language ? `<span class="text-xs px-2 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-700/60 font-medium">${escapeHtml(movie.language)}</span>` : ''}
              ${movie.year ? `<span class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">${movie.year}</span>` : ''}
            </div>
            <p class="text-xs text-indigo-400 font-medium truncate max-w-sm sm:max-w-md">${escapeHtml(movie.album_title || 'Original Motion Picture Soundtrack')}</p>
            <p class="text-xs text-slate-400 mt-0.5 flex items-center gap-1.5">
              <i data-lucide="user" class="w-3 h-3 text-slate-500"></i>
              <span>${escapeHtml(movie.artist || 'Various Artists')}</span>
            </p>
          </div>
        </div>

        <div class="flex items-center space-x-3 self-end sm:self-center">
          ${movie.artwork_url ? `
            <button onclick="downloadCoverImage('${movie.artwork_url}', '${escapeHtml(movie.movie_query)}')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] border border-slate-700 flex items-center gap-1.5 transition" title="Download High-Res Cover Art">
              <i data-lucide="image" class="w-3.5 h-3.5 text-pink-400"></i>
              <span>Cover Art</span>
            </button>
          ` : ''}
          <label class="text-xs text-slate-400 flex items-center gap-1.5 cursor-pointer hover:text-slate-200">
            <input type="checkbox" checked data-movie-index="${movieIndex}" class="movie-select-all rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-indigo-500">
            <span>Select All (${movie.tracks.length})</span>
          </label>
        </div>
      </div>

      <!-- Tracks Table -->
      <div class="divide-y divide-slate-800/40 overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-950/40 text-slate-400 uppercase text-[10px] tracking-wider">
            <tr>
              <th class="py-2.5 px-4 w-10"></th>
              <th class="py-2.5 px-3 w-12 text-center">#</th>
              <th class="py-2.5 px-4">Title</th>
              <th class="py-2.5 px-4">Artist / Singers</th>
              <th class="py-2.5 px-4 text-right">Duration</th>
              <th class="py-2.5 px-4 w-20 text-center">Preview</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/30">
            ${movie.tracks.map((track, trackIndex) => `
              <tr class="hover:bg-slate-800/30 transition group" id="row-${track.id}">
                <td class="py-2.5 px-4">
                  <input type="checkbox" checked data-movie-index="${movieIndex}" data-track-index="${trackIndex}" class="track-checkbox rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-indigo-500">
                </td>
                <td class="py-2.5 px-3 text-slate-500 font-mono text-center">
                  ${track.track_number || (trackIndex + 1)}
                </td>
                <td class="py-2.5 px-4 font-medium text-slate-200">
                  ${escapeHtml(track.title)}
                </td>
                <td class="py-2.5 px-4 text-slate-400">
                  ${escapeHtml(track.artist)}
                </td>
                <td class="py-2.5 px-4 text-slate-400 font-mono text-right">
                  ${track.duration_formatted}
                </td>
                <td class="py-2.5 px-4 text-center">
                  ${track.preview_url ? `
                    <button onclick="toggleAudioPreview('${track.id}', '${track.preview_url}', this)" class="p-1.5 rounded-lg bg-slate-800 hover:bg-indigo-600 text-slate-300 hover:text-white transition" title="Listen 30s preview">
                      <i data-lucide="play" class="w-3.5 h-3.5"></i>
                    </button>
                  ` : `
                    <span class="text-slate-600 text-[10px]">-</span>
                  `}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;

    movieCardsContainer.appendChild(card);
  });

  // Attach movie checkbox listeners
  document.querySelectorAll(".movie-select-all").forEach(cb => {
    cb.addEventListener("change", (e) => {
      const movieIdx = e.target.getAttribute("data-movie-index");
      const trackCheckboxes = document.querySelectorAll(`.track-checkbox[data-movie-index="${movieIdx}"]`);
      trackCheckboxes.forEach(tcb => { tcb.checked = e.target.checked; });
    });
  });

  resultsSection.classList.remove("hidden");
  lucide.createIcons();
}

function escapeHtml(text) {
  if (!text) return "";
  return text.replace(/[&<>"']/g, function(m) {
    return {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    }[m];
  });
}

// Audio Preview Player
window.toggleAudioPreview = function(trackId, previewUrl, buttonElement) {
  if (currentlyPlayingTrackId === trackId) {
    stopAudio();
    return;
  }

  stopAudio();

  currentlyPlayingTrackId = trackId;
  audioPlayer.src = previewUrl;
  audioPlayer.play().catch(e => console.log("Audio play error:", e));

  buttonElement.innerHTML = `<i data-lucide="square" class="w-3.5 h-3.5 text-pink-400"></i>`;
  buttonElement.classList.add("bg-pink-600/30");
  lucide.createIcons();

  audioPlayer.onended = () => {
    stopAudio();
  };
};

function stopAudio() {
  if (currentlyPlayingTrackId) {
    audioPlayer.pause();
    audioPlayer.currentTime = 0;
    // reset button icon
    document.querySelectorAll(`button[onclick*="${currentlyPlayingTrackId}"]`).forEach(btn => {
      btn.innerHTML = `<i data-lucide="play" class="w-3.5 h-3.5"></i>`;
      btn.classList.remove("bg-pink-600/30");
    });
    currentlyPlayingTrackId = null;
    lucide.createIcons();
  }
}

// Filter currently checked movies and tracks
function getSelectedMovieResults() {
  const selectedResults = [];

  currentSearchResults.forEach((movie, movieIdx) => {
    if (!movie.found || !movie.tracks) return;

    const checkedTracks = [];
    movie.tracks.forEach((track, trackIdx) => {
      const cb = document.querySelector(`.track-checkbox[data-movie-index="${movieIdx}"][data-track-index="${trackIdx}"]`);
      if (cb && cb.checked) {
        checkedTracks.push(track);
      }
    });

    if (checkedTracks.length > 0) {
      selectedResults.push({
        ...movie,
        total_tracks: checkedTracks.length,
        tracks: checkedTracks
      });
    }
  });

  return selectedResults;
}

// Export Tracklist (CSV, TXT, JSON)
async function exportTracklist(format) {
  const selected = getSelectedMovieResults();
  if (selected.length === 0) {
    alert("Please select at least one song to export.");
    return;
  }

  try {
    const response = await fetch("/api/export/tracklist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        results: selected,
        format: format
      })
    });

    if (!response.ok) {
      throw new Error("Failed to export tracklist.");
    }

    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `movie_soundtracks.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(downloadUrl);
  } catch (error) {
    alert(`Export error: ${error.message}`);
  }
}

document.getElementById("exportCsvBtn").addEventListener("click", () => exportTracklist("csv"));
document.getElementById("exportTxtBtn").addEventListener("click", () => exportTracklist("txt"));
document.getElementById("exportJsonBtn").addEventListener("click", () => exportTracklist("json"));

// Download Audio ZIP (yt-dlp)
const progressModal = document.getElementById("progressModal");
const modalCurrentTrack = document.getElementById("modalCurrentTrack");
const modalPercentage = document.getElementById("modalPercentage");
const modalProgressBar = document.getElementById("modalProgressBar");
const modalCounts = document.getElementById("modalCounts");
const modalSuccessBox = document.getElementById("modalSuccessBox");
const modalErrorBox = document.getElementById("modalErrorBox");
const modalErrorText = document.getElementById("modalErrorText");
const closeModalBtn = document.getElementById("closeModalBtn");
const modalDoneBtn = document.getElementById("modalDoneBtn");

closeModalBtn.addEventListener("click", closeProgressModal);
modalDoneBtn.addEventListener("click", closeProgressModal);

function closeProgressModal() {
  progressModal.classList.add("hidden");
  if (downloadPollInterval) {
    clearInterval(downloadPollInterval);
    downloadPollInterval = null;
  }
}

window.downloadCoverImage = async function(url, movieName) {
  if (!url) return;
  try {
    const resp = await fetch(url);
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = window.URL.createObjectURL(blob);
    a.download = `${movieName}_cover.jpg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    window.open(url, "_blank");
  }
};

document.getElementById("downloadZipBtn").addEventListener("click", async () => {
  const selected = getSelectedMovieResults();
  if (selected.length === 0) {
    alert("Please select at least one song to download.");
    return;
  }

  const audioQualitySelect = document.getElementById("audioQualitySelect");
  const audioQuality = audioQualitySelect ? audioQualitySelect.value : "mp3_320";

  const totalTracks = selected.reduce((sum, m) => sum + m.tracks.length, 0);
  if (totalTracks > 40) {
    const confirmBig = confirm(`You have selected ${totalTracks} songs. Downloading this many audio files may take several minutes. Continue?`);
    if (!confirmBig) return;
  }

  // Open modal
  progressModal.classList.remove("hidden");
  modalSuccessBox.classList.add("hidden");
  modalErrorBox.classList.add("hidden");
  modalProgressBar.style.width = "0%";
  modalPercentage.innerText = "0%";
  const qualityLabel = audioQuality === "flac" ? "Lossless FLAC" : (audioQuality === "mp3_320" ? "320 kbps MP3" : "192 kbps MP3");
  modalCurrentTrack.innerText = `Starting parallel download (${qualityLabel})...`;
  modalCounts.innerText = `0 / ${totalTracks} tracks`;
  lucide.createIcons();

  try {
    const response = await fetch("/api/export/audio-zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ results: selected, audio_quality: audioQuality })
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Failed to initiate download job.");
    }

    const data = await response.json();
    const taskId = data.task_id;

    // Start polling status
    pollDownloadStatus(taskId);

  } catch (error) {
    modalErrorBox.classList.remove("hidden");
    modalErrorText.innerText = error.message;
    lucide.createIcons();
  }
});

function pollDownloadStatus(taskId) {
  if (downloadPollInterval) clearInterval(downloadPollInterval);

  downloadPollInterval = setInterval(async () => {
    try {
      const resp = await fetch(`/api/export/audio-zip/status/${taskId}`);
      if (!resp.ok) return;

      const status = await resp.json();
      const progress = status.progress || 0;

      modalProgressBar.style.width = `${progress}%`;
      modalPercentage.innerText = `${progress}%`;
      modalCurrentTrack.innerText = status.current_track || "Processing...";
      modalCounts.innerText = `${status.completed_tracks || 0} / ${status.total_tracks || 0} tracks`;

      if (status.status === "completed") {
        clearInterval(downloadPollInterval);
        downloadPollInterval = null;
        modalSuccessBox.classList.remove("hidden");
        lucide.createIcons();

        // Trigger direct browser download
        const a = document.createElement("a");
        a.href = `/api/export/audio-zip/download/${taskId}`;
        a.download = status.filename || "soundtracks.zip";
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else if (status.status === "failed") {
        clearInterval(downloadPollInterval);
        downloadPollInterval = null;
        modalErrorBox.classList.remove("hidden");
        modalErrorText.innerText = status.error || "Download failed.";
        lucide.createIcons();
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 1000);
}

