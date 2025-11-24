// script.js — Voice-only interview (Avatar centered, think->auto-record->silence stop)
const API_BASE = "http://127.0.0.1:8000";
const AVATAR_URL = "assets/interviewer.webp";

// DOM
const videoEl = document.getElementById("camera");
const statusEl = document.getElementById("status");
const micFill = document.getElementById("mic-fill");
const avatarWrap = document.getElementById("avatarWrap");
const avatarImg = document.getElementById("avatar");
const avatarGlow = document.getElementById("avatarGlow");
const snico = document.getElementById("snico");
const endBtn = document.getElementById("endBtn");

// runtime state
let masterStream = null;
let audioOnlyStream = null;
let recorder = null;
let recordedChunks = [];
let isRecording = false;

let audioCtxMeter = null;
let analyserMeter = null;
let meterData = null;
let rmsSmoothed = 0;

let audioCtxSilence = null;
let analyserSilence = null;
let silenceThreshold = 0.02; // fallback

const THINK_SECONDS = 15;
const SILENCE_MS = 6000;
const MAX_ANSWER_MS = 90_000;

// Set avatar image
avatarImg.src = AVATAR_URL;

// Build Snico bars
function buildSnico(n = 18) {
    snico.innerHTML = "";
    for (let i = 0; i < n; i++) {
        const b = document.createElement("div");
        b.className = "bar";
        b.style.height = "8px";
        snico.appendChild(b);
    }
}
buildSnico(20);

// Convert hex audio → play sound
function playServerHex(hexStr, onStart = null, onEnd = null) {
    if (!hexStr) { if (onEnd) onEnd(); return; }
    try {
        const bytes = new Uint8Array(hexStr.match(/.{1,2}/g).map(h => parseInt(h, 16)));
        const blob = new Blob([bytes], { type: "audio/mpeg" });
        const url = URL.createObjectURL(blob);
        const a = new Audio(url);

        a.onplay = () => { if (onStart) onStart(); };
        a.onended = () => { if (onEnd) onEnd(); URL.revokeObjectURL(url); };

        a.play().catch(e => { console.warn("Playback failed:", e); if (onEnd) onEnd(); });
    } catch (e) {
        console.error("playServerHex error", e);
        if (onEnd) onEnd();
    }
}

// ❗ FIXED: Snico animates ONLY when interviewer speaks
function setInterviewerSpeaking(on) {
    const bars = Array.from(document.querySelectorAll("#snico .bar"));

    if (on) {
        avatarWrap.classList.add("avatar-active");

        snico._talkInterval = setInterval(() => {
            bars.forEach((b, i) => {
                const h = 12 + Math.random() * 40;
                b.style.height = `${h}px`;
            });
        }, 120);

    } else {
        avatarWrap.classList.remove("avatar-active");

        clearInterval(snico._talkInterval);
        bars.forEach(b => b.style.height = "8px");
    }
}

// ❗ FIXED: User meter ONLY updates mic bar — NO Snico movement
function updateUserVisuals(level) {
    micFill.style.width = Math.min(100, Math.round(level * 100)) + "%";
}

// Setup camera + mic
async function setupMedia() {
    if (masterStream) return;
    statusEl.textContent = "Requesting camera & mic permission…";

    try {
        masterStream = await navigator.mediaDevices.getUserMedia({
            audio: true,
            video: { width: 1280 }
        });

        videoEl.srcObject = masterStream;
        audioOnlyStream = new MediaStream(masterStream.getAudioTracks());
        statusEl.textContent = "Ready";

        initMeter(audioOnlyStream);

    } catch (e) {
        console.error("Media error:", e);
        statusEl.textContent = "Allow camera & mic";
        alert("Please allow camera and microphone access.");
    }
}

// Mic meter animation (user only)
function initMeter(stream) {
    try {
        audioCtxMeter = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtxMeter.createMediaStreamSource(stream);
        analyserMeter = audioCtxMeter.createAnalyser();
        analyserMeter.fftSize = 1024;

        src.connect(analyserMeter);
        meterData = new Uint8Array(analyserMeter.fftSize);

        (function drawMeter() {
            analyserMeter.getByteTimeDomainData(meterData);

            let sum = 0;
            for (let i = 0; i < meterData.length; i++) {
                const v = (meterData[i] - 128) / 128;
                sum += v * v;
            }
            const rms = Math.sqrt(sum / meterData.length);

            rmsSmoothed = rmsSmoothed * 0.85 + rms * 0.15;
            updateUserVisuals(Math.min(1, rmsSmoothed * 4));

            requestAnimationFrame(drawMeter);
        })();

    } catch (e) {
        console.warn("Meter error:", e);
    }
}

// Ambient calibration
function calibrateAmbient(stream) {
    return new Promise((resolve) => {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const src = ctx.createMediaStreamSource(stream);
            const a = ctx.createAnalyser();
            a.fftSize = 1024;
            src.connect(a);

            const data = new Uint8Array(a.fftSize);
            const samples = [];
            const start = performance.now();

            (function sample() {
                a.getByteTimeDomainData(data);
                let sum = 0;
                for (let i = 0; i < data.length; i++) {
                    const v = (data[i] - 128) / 128;
                    sum += v * v;
                }
                samples.push(Math.sqrt(sum / data.length));

                if (performance.now() - start < 700)
                    requestAnimationFrame(sample);
                else {
                    const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
                    resolve(Math.max(0.003, avg * 2.2));
                    ctx.close();
                }

            })();

        } catch (e) {
            console.warn("Ambient fallback:", e);
            resolve(0.02);
        }
    });
}

// Start interview
async function startInterview() {
    statusEl.textContent = "Contacting server...";

    try {
        const res = await fetch(API_BASE + "/api/start", { method: "POST" });
        const j = await res.json();

        const hex = j.ai_audio_b64 || j.ai_audio;
        playServerHex(
            hex,
            () => { setInterviewerSpeaking(true); statusEl.textContent = "Interviewer speaking…"; },
            () => {
                setInterviewerSpeaking(false);
                statusEl.textContent = "Thinking (15s)…";
                startThinkingTimer();
            }
        );

    } catch (e) {
        console.error(e);
        statusEl.textContent = "Server unreachable";
    }
}

// Thinking countdown
function startThinkingTimer() {
    let t = THINK_SECONDS;
    statusEl.textContent = `Think… ${t}s`;

    const iv = setInterval(() => {
        t--;
        if (t > 0) statusEl.textContent = `Think… ${t}s`;
        else {
            clearInterval(iv);
            startRecordingAuto();
        }
    }, 1000);
}

// Start recording + silence detection
async function startRecordingAuto() {
    if (!audioOnlyStream) return;

    statusEl.textContent = "Calibrating mic…";
    silenceThreshold = await calibrateAmbient(audioOnlyStream);

    try {
        recorder = new MediaRecorder(audioOnlyStream, { mimeType: "audio/webm" });
    } catch {
        recorder = new MediaRecorder(audioOnlyStream);
    }

    recordedChunks = [];
    recorder.ondataavailable = e => recordedChunks.push(e.data);
    recorder.onstop = onRecorderStop;

    recorder.start();
    isRecording = true;
    statusEl.textContent = "Recording… (max 90s)";

    startSilenceMonitor(silenceThreshold);

    setTimeout(() => {
        if (isRecording) stopRecordingAuto();
    }, MAX_ANSWER_MS);
}

// Silence detection engine
function startSilenceMonitor(threshold) {
    try {
        audioCtxSilence = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtxSilence.createMediaStreamSource(audioOnlyStream);
        analyserSilence = audioCtxSilence.createAnalyser();
        analyserSilence.fftSize = 2048;

        const data = new Uint8Array(analyserSilence.fftSize);
        let silenceStart = null;

        (function poll() {
            analyserSilence.getByteTimeDomainData(data);

            let sum = 0;
            for (let i = 0; i < data.length; i++) {
                const v = (data[i] - 128) / 128;
                sum += v * v;
            }
            const rms = Math.sqrt(sum / data.length);
            rmsSmoothed = rmsSmoothed * 0.8 + rms * 0.2;

            if (rmsSmoothed < threshold) {
                if (!silenceStart) silenceStart = performance.now();
                else if (performance.now() - silenceStart >= SILENCE_MS) {
                    stopRecordingAuto();
                    audioCtxSilence.close();
                    return;
                }
            } else {
                silenceStart = null;
            }

            if (isRecording) requestAnimationFrame(poll);

        })();

    } catch (e) {
        console.warn("Silence monitor error:", e);
    }
}

// Stop recording
function stopRecordingAuto() {
    if (!recorder || !isRecording) return;
    isRecording = false;

    if (recorder.state === "recording") recorder.stop();
    statusEl.textContent = "Processing upload…";
}

// Upload and play interviewer response
async function onRecorderStop() {
    const blob = new Blob(recordedChunks, { type: "audio/webm" });
    const fd = new FormData();
    fd.append("audio", blob, "answer.webm");

    try {
        const res = await fetch(API_BASE + "/api/send_audio", { method: "POST", body: fd });
        const j = await res.json();

        const hex = j.ai_audio_b64 || j.ai_audio;

        playServerHex(
            hex,
            () => { setInterviewerSpeaking(true); statusEl.textContent = "Interviewer speaking…"; },
            () => {
                setInterviewerSpeaking(false);

                if (j.expect_more !== false) {
                    statusEl.textContent = "Thinking (15s)…";
                    startThinkingTimer();
                } else {
                    statusEl.textContent = "Interview complete.";
                    setInterviewerSpeaking(false);
                    setTimeout(() => {
                    alert("🎉 Thank you! The interview is complete.");
                }, 500);
                }
            }
        );

    } catch (e) {
        console.error(e);
        statusEl.textContent = "Upload failed";
    } finally {
        recordedChunks = [];
        if (audioCtxSilence) audioCtxSilence.close();
    }
}

// End button
endBtn.addEventListener("click", () => {
    if (isRecording) stopRecordingAuto();
    statusEl.textContent = "Interview ended by user.";
    fetch(API_BASE + "/api/end", { method: "POST" }).catch(() => { });
});

// Init
window.addEventListener("load", async () => {
    statusEl.textContent = "Starting…";
    await setupMedia();
    setTimeout(startInterview, 350);
});
