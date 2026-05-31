document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const toggleUrl = document.getElementById("toggleUrl");
  const toggleUpload = document.getElementById("toggleUpload");
  const urlInputGroup = document.getElementById("urlInputGroup");
  const uploadInputGroup = document.getElementById("uploadInputGroup");
  const youtubeUrlInput = document.getElementById("youtubeUrl");
  const videoFileInput = document.getElementById("videoFileInput");
  const dropZone = document.getElementById("dropZone");
  const fileInfo = document.getElementById("fileInfo");
  const fileName = document.getElementById("fileName");
  const removeFileBtn = document.getElementById("removeFileBtn");
  
  const pipelineForm = document.getElementById("pipelineForm");
  const topNSelect = document.getElementById("topN");
  const forceRerunCheckbox = document.getElementById("forceRerun");
  const submitBtn = document.getElementById("submitBtn");
  const submitBtnText = submitBtn.querySelector(".btn-text");
  const submitBtnSpinner = submitBtn.querySelector(".btn-spinner");
  
  const progressPanel = document.getElementById("progressPanel");
  const inputPanel = document.querySelector(".input-panel");
  const resultsPanel = document.getElementById("resultsPanel");
  
  const jobTitle = document.getElementById("jobTitle");
  const progressPercentage = document.getElementById("progressPercentage");
  const progressRingCircle = document.querySelector(".progress-ring__circle");
  const consoleBox = document.getElementById("consoleBox");
  
  const shortsGrid = document.getElementById("shortsGrid");
  const shortDetailsCard = document.getElementById("shortDetailsCard");
  const backToInputBtn = document.getElementById("backToInputBtn");
  const historyList = document.getElementById("historyList");
  
  const toast = document.getElementById("toast");

  // State
  let activeInputMode = "url"; // 'url' or 'upload'
  let selectedFile = null;
  let pollIntervalId = null;
  let activeVideoId = null;
  let autoScrollLogs = true;

  // Circle progress calculation
  const radius = progressRingCircle.r.baseVal.value;
  const circumference = radius * 2 * Math.PI;
  progressRingCircle.style.strokeDasharray = `${circumference} ${circumference}`;
  progressRingCircle.style.strokeDashoffset = circumference;

  function setProgress(percent) {
    const offset = circumference - (percent / 100) * circumference;
    progressRingCircle.style.strokeDashoffset = offset;
    progressPercentage.textContent = `${Math.round(percent)}%`;
  }

  // Toast Helper
  function showToast(message, isError = false) {
    toast.textContent = message;
    toast.style.borderColor = isError ? "var(--color-error)" : "var(--border-glass)";
    toast.classList.remove("hidden");
    
    // Animate
    toast.style.transform = "translateX(-50%) translateY(-10px)";
    toast.style.opacity = "1";

    setTimeout(() => {
      toast.style.transform = "translateX(-50%) translateY(0)";
      toast.style.opacity = "0";
      setTimeout(() => {
        toast.classList.add("hidden");
      }, 300);
    }, 2500);
  }

  // Toggle URL vs Upload Form Modes
  toggleUrl.addEventListener("click", () => {
    activeInputMode = "url";
    toggleUrl.classList.add("active");
    toggleUpload.classList.remove("active");
    urlInputGroup.classList.remove("hidden");
    uploadInputGroup.classList.add("hidden");
    youtubeUrlInput.required = true;
  });

  toggleUpload.addEventListener("click", () => {
    activeInputMode = "upload";
    toggleUpload.classList.add("active");
    toggleUrl.classList.remove("active");
    uploadInputGroup.classList.remove("hidden");
    urlInputGroup.classList.add("hidden");
    youtubeUrlInput.required = false;
  });

  // Drag and Drop File Handlers
  dropZone.addEventListener("click", () => {
    videoFileInput.click();
  });

  videoFileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileSelection(e.target.files[0]);
    }
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileSelection(e.dataTransfer.files[0]);
    }
  });

  function handleFileSelection(file) {
    if (!file.type.startsWith("video/") && !file.name.toLowerCase().endsWith(".mp4") && !file.name.toLowerCase().endsWith(".mov") && !file.name.toLowerCase().endsWith(".mkv") && !file.name.toLowerCase().endsWith(".avi")) {
      showToast("Only video files (MP4, MOV, MKV, AVI) are supported.", true);
      return;
    }
    selectedFile = file;
    fileName.textContent = file.name;
    fileInfo.classList.remove("hidden");
    dropZone.querySelector(".upload-icon").textContent = "🎬";
    dropZone.querySelector(".upload-text").innerHTML = `Selected: <strong>${file.name}</strong>`;
  }

  removeFileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    selectedFile = null;
    videoFileInput.value = "";
    fileInfo.classList.add("hidden");
    dropZone.querySelector(".upload-icon").textContent = "📤";
    dropZone.querySelector(".upload-text").innerHTML = 'Drag & drop your video here, or <span class="browse-link">browse</span>';
  });

  // Load Past Runs Library
  async function loadHistory() {
    try {
      const resp = await fetch("/api/history");
      const list = await resp.json();
      
      if (list.length === 0) {
        historyList.innerHTML = '<div class="empty-state">No previous runs found.</div>';
        return;
      }
      
      historyList.innerHTML = "";
      list.forEach(item => {
        const div = document.createElement("div");
        div.className = "history-item";
        div.dataset.id = item.video_id;
        
        div.innerHTML = `
          <h4>${item.title || item.video_id}</h4>
          <p>${item.uploader || "Local Run"} • ${item.shorts_count} Shorts</p>
        `;
        
        div.addEventListener("click", () => {
          document.querySelectorAll(".history-item").forEach(el => el.classList.remove("active"));
          div.classList.add("active");
          displayResults(item.video_id, item.shorts, item.title);
        });
        historyList.appendChild(div);
      });
    } catch (err) {
      console.error("Failed to load runs history", err);
    }
  }

  // Handle Form Submission
  pipelineForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const topN = parseInt(topNSelect.value, 10);
    const force = forceRerunCheckbox.checked;

    // Toggle button load state
    submitBtn.disabled = true;
    submitBtnText.textContent = "Launching Pipeline...";
    submitBtnSpinner.classList.remove("hidden");

    try {
      let videoId = "";
      
      if (activeInputMode === "url") {
        const youtubeUrl = youtubeUrlInput.value.trim();
        const resp = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ youtube_url: youtubeUrl, top_n: topN, force: force })
        });
        
        if (!resp.ok) {
          const detail = await resp.json();
          throw new Error(detail.detail || "Failed to trigger YouTube run");
        }
        
        const data = await resp.json();
        videoId = data.video_id;
      } else {
        // File upload mode
        if (!selectedFile) {
          throw new Error("Please select a video file to upload.");
        }
        
        const formData = new FormData();
        formData.append("file", selectedFile);
        
        const resp = await fetch(`/api/upload?top_n=${topN}&force=${force}`, {
          method: "POST",
          body: formData
        });
        
        if (!resp.ok) {
          const detail = await resp.json();
          throw new Error(detail.detail || "Failed to upload video file");
        }
        
        const data = await resp.json();
        videoId = data.video_id;
      }

      // Enter active progress stage
      startProgressTracking(videoId);

    } catch (err) {
      showToast(err.message, true);
      submitBtn.disabled = false;
      submitBtnText.textContent = "Generate Shorts";
      submitBtnSpinner.classList.add("hidden");
    }
  });

  // Track active run progress
  function startProgressTracking(videoId) {
    activeVideoId = videoId;
    inputPanel.classList.add("hidden");
    resultsPanel.classList.add("hidden");
    progressPanel.classList.remove("hidden");
    
    // Clear logs
    consoleBox.innerHTML = '<div class="log-line system">Initializing local workspace...</div>';
    setProgress(0);

    // Reset pipeline steps visual states
    document.querySelectorAll(".step").forEach(step => {
      step.className = "step";
    });

    jobTitle.textContent = activeInputMode === "url" ? "Processing YouTube Video" : "Processing Uploaded Video";

    // Poll status endpoint
    pollIntervalId = setInterval(async () => {
      try {
        const resp = await fetch(`/api/status/${videoId}`);
        const state = await resp.json();
        
        // Update Ring and Percentage
        setProgress(state.progress);

        // Update active step timeline
        updateStepper(state.status);

        // Render Logs
        renderLogs(state.logs);

        if (state.status === "completed") {
          clearInterval(pollIntervalId);
          showToast("Pipeline completed successfully!");
          displayResults(videoId, state.shorts, state.title || "Clips Generated");
          loadHistory(); // refresh history list
        } else if (state.status === "failed") {
          clearInterval(pollIntervalId);
          showToast(`Pipeline failed: ${state.error}`, true);
          submitBtn.disabled = false;
          submitBtnText.textContent = "Generate Shorts";
          submitBtnSpinner.classList.add("hidden");
          
          // Show error log line
          const errDiv = document.createElement("div");
          errDiv.className = "log-line error";
          errDiv.textContent = `CRITICAL FAILURE: ${state.error}`;
          consoleBox.appendChild(errDiv);
        }

      } catch (err) {
        console.error("Error polling job status", err);
      }
    }, 1000);
  }

  // Update Visual Stages stepper
  function updateStepper(status) {
    const stepsMap = {
      "starting": ["step-downloading"],
      "downloading": ["step-downloading"],
      "heatmap": ["step-heatmap"],
      "transcribing": ["step-transcribing"],
      "segmenting": ["step-segmenting"],
      "scoring": ["step-scoring"],
      "ranking": ["step-scoring"],
      "face_tracking": ["step-face_tracking"],
      "cropping": ["step-cropping"],
      "subtitling": ["step-subtitling"],
      "exporting": ["step-exporting"],
      "completed": ["step-exporting"]
    };

    const orderedSteps = [
      "step-downloading",
      "step-heatmap",
      "step-transcribing",
      "step-segmenting",
      "step-scoring",
      "step-face_tracking",
      "step-cropping",
      "step-subtitling",
      "step-exporting"
    ];

    const activeSteps = stepsMap[status] || [];
    const activeStepId = activeSteps[0];
    const activeIndex = orderedSteps.indexOf(activeStepId);

    orderedSteps.forEach((stepId, index) => {
      const element = document.getElementById(stepId);
      if (!element) return;

      if (status === "completed") {
        element.className = "step completed";
      } else if (index < activeIndex) {
        element.className = "step completed";
      } else if (index === activeIndex) {
        element.className = "step active";
      } else {
        element.className = "step";
      }
    });
  }

  // Render logs line-by-line
  let lastLogCount = 0;
  function renderLogs(logs) {
    if (!logs || logs.length === 0) return;
    
    // Only append new logs
    if (logs.length > lastLogCount) {
      for (let i = lastLogCount; i < logs.length; i++) {
        const line = logs[i];
        const div = document.createElement("div");
        div.className = "log-line";
        
        // Highlight specific levels
        if (line.includes("ERROR") || line.includes("failed")) {
          div.classList.add("error");
        } else if (line.includes("Done.") || line.includes("complete")) {
          div.classList.add("success");
        } else if (line.includes("Stage")) {
          div.classList.add("system");
        }
        
        div.textContent = line;
        consoleBox.appendChild(div);
      }
      lastLogCount = logs.length;

      if (autoScrollLogs) {
        consoleBox.scrollTop = consoleBox.scrollHeight;
      }
    }
  }

  document.getElementById("scrollLogBtn").addEventListener("click", () => {
    autoScrollLogs = !autoScrollLogs;
    document.getElementById("scrollLogBtn").textContent = autoScrollLogs ? "Auto-scroll" : "Locked";
    document.getElementById("scrollLogBtn").style.color = autoScrollLogs ? "var(--color-secondary)" : "var(--text-dark)";
  });

  // Display results dashboard
  function displayResults(videoId, shorts, title) {
    progressPanel.classList.add("hidden");
    inputPanel.classList.add("hidden");
    resultsPanel.classList.remove("hidden");

    resultsTitle.textContent = title || "Output Shorts";
    shortsGrid.innerHTML = "";

    if (!shorts || shorts.length === 0) {
      shortsGrid.innerHTML = '<div class="empty-state">No shorts generated. Check logs.</div>';
      shortDetailsCard.innerHTML = `
        <div class="details-empty-state">
          <span>⚠️</span>
          <p>No segment data generated. Check output/metadata.json for results.</p>
        </div>
      `;
      return;
    }

    // Default details empty view
    shortDetailsCard.innerHTML = `
      <div class="details-empty-state">
        <span>👈</span>
        <p>Select a generated short card from the grid to view captions, virality scores, and sharing metadata.</p>
      </div>
    `;

    shorts.forEach((short, index) => {
      const card = document.createElement("div");
      card.className = "short-card";
      
      const score = (short.llm_scores && short.llm_scores.final) || 0.0;
      const formattedScore = score.toFixed(1);
      
      // Serve video path
      const videoSrc = `/output/${videoId}/${short.filename}`;

      card.innerHTML = `
        <div class="card-score-badge">★ ${formattedScore}</div>
        <div class="video-thumb-container">
          <video src="${videoSrc}" preload="metadata" muted playsinline></video>
        </div>
        <div class="short-card-info">
          <h4>Short #${index + 1}</h4>
          <p>${short.duration.toFixed(1)}s • Start: ${short.source_start.toFixed(1)}s</p>
        </div>
      `;

      // Hover to preview play
      const video = card.querySelector("video");
      card.addEventListener("mouseenter", () => {
        video.play().catch(() => {});
      });
      card.addEventListener("mouseleave", () => {
        video.pause();
        video.currentTime = 0;
      });

      // Click to load details panel
      card.addEventListener("click", () => {
        document.querySelectorAll(".short-card").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        displayShortDetails(videoId, short);
      });

      shortsGrid.appendChild(card);
    });
  }

  // Display details panel for a single short
  function displayShortDetails(videoId, short) {
    const videoSrc = `/output/${videoId}/${short.filename}`;
    
    // Scores
    const hook = (short.llm_scores && short.llm_scores.hook) || 0;
    const standalone = (short.llm_scores && short.llm_scores.standalone) || 0;
    const emotion = (short.llm_scores && short.llm_scores.emotion) || 0;
    const quotability = (short.llm_scores && short.llm_scores.quotability) || 0;
    const pacing = (short.llm_scores && short.llm_scores.pacing) || 0;
    const finalScore = (short.llm_scores && short.llm_scores.final) || 0;

    const tagsHtml = (short.suggested_hashtags || []).map(t => `<span class="tag">${t}</span>`).join("");

    shortDetailsCard.innerHTML = `
      <div class="details-header">
        <h3>Short Details</h3>
        <p>File: <strong>${short.filename}</strong> (${short.duration.toFixed(1)}s)</p>
      </div>

      <div class="video-preview-wrapper" style="aspect-ratio: 9/16; border-radius: 8px; overflow: hidden; background: black; border: 1px solid var(--border-glass)">
        <video src="${videoSrc}" controls style="width: 100%; height: 100%; object-fit: cover"></video>
      </div>

      <!-- LLM scores visual bar charts -->
      <div class="scores-breakdown">
        <h4 style="font-size: 11px; color: var(--text-dark); text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.5px">Virality Scores</h4>
        
        <div class="score-row">
          <div class="score-info"><span>Hook Ratio</span><span class="score-val">${hook}/10</span></div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width: ${hook * 10}%"></div></div>
        </div>
        <div class="score-row">
          <div class="score-info"><span>Standalone</span><span class="score-val">${standalone}/10</span></div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width: ${standalone * 10}%"></div></div>
        </div>
        <div class="score-row">
          <div class="score-info"><span>Emotional Resonance</span><span class="score-val">${emotion}/10</span></div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width: ${emotion * 10}%"></div></div>
        </div>
        <div class="score-row">
          <div class="score-info"><span>Quotability</span><span class="score-val">${quotability}/10</span></div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width: ${quotability * 10}%"></div></div>
        </div>
        <div class="score-row">
          <div class="score-info"><span>Energy Pacing</span><span class="score-val">${pacing}/10</span></div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width: ${pacing * 10}%"></div></div>
        </div>
      </div>

      <!-- Virality Reason -->
      <div class="reason-box">
        <h5>AI Virality Rationale</h5>
        <p>${short.reason || "High scoring candidate segment."}</p>
      </div>

      <!-- Suggested Captions and Copy buttons -->
      <div class="metadata-panel">
        <div class="metadata-box">
          <h5>Suggested Reels Caption</h5>
          <p id="captionText">${short.suggested_caption || "Check out this amazing segment!"}</p>
          <button class="copy-icon-btn" id="copyCaptionBtn" title="Copy Caption">📋</button>
        </div>

        <div class="metadata-box">
          <h5>Suggested Hashtags</h5>
          <div class="tags-container">${tagsHtml || '<span class="tag">#shorts</span>'}</div>
          <button class="copy-icon-btn" id="copyTagsBtn" title="Copy Hashtags">📋</button>
        </div>
      </div>
    `;

    // Event listener for copies
    const copyCaptionBtn = shortDetailsCard.querySelector("#copyCaptionBtn");
    const copyTagsBtn = shortDetailsCard.querySelector("#copyTagsBtn");

    copyCaptionBtn.addEventListener("click", () => {
      const captionText = shortDetailsCard.querySelector("#captionText").textContent;
      navigator.clipboard.writeText(captionText).then(() => {
        showToast("Caption copied to clipboard!");
      });
    });

    copyTagsBtn.addEventListener("click", () => {
      const tagsText = (short.suggested_hashtags || []).join(" ");
      navigator.clipboard.writeText(tagsText).then(() => {
        showToast("Hashtags copied to clipboard!");
      });
    });
  }

  // Back to input page
  backToInputBtn.addEventListener("click", () => {
    resultsPanel.classList.add("hidden");
    inputPanel.classList.remove("hidden");
    
    // Reset form states
    submitBtn.disabled = false;
    submitBtnText.textContent = "Generate Shorts";
    submitBtnSpinner.classList.add("hidden");
    
    // Clear selections
    selectedFile = null;
    videoFileInput.value = "";
    fileInfo.classList.add("hidden");
    dropZone.querySelector(".upload-icon").textContent = "📤";
    dropZone.querySelector(".upload-text").innerHTML = 'Drag & drop your video here, or <span class="browse-link">browse</span>';
    youtubeUrlInput.value = "";
  });

  // Init Load
  loadHistory();
});
