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
let silenceTimer = null;

const THINK_SECONDS = 15;
const SILENCE_MS = 6000;   // stop after 6s sustained silence
const MAX_ANSWER_MS = 90_000; // 90 seconds

// set avatar image
avatarImg.src = AVATAR_URL;

// create snico bars
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

// tiny helper to play server audio which is returned as hex string
function playServerHex(hexStr, onStart = null, onEnd = null) {
    if (!hexStr) { if (onEnd) onEnd(); return; }
    try {
        // hex->bytes
        const bytes = new Uint8Array(hexStr.match(/.{1,2}/g).map(h => parseInt(h, 16)));
        const blob = new Blob([bytes], { type: "audio/mpeg" });
        const url = URL.createObjectURL(blob);
        const a = new Audio(url);
        a.onplay = () => { if (onStart) onStart(); };
        a.onended = () => { if (onEnd) onEnd(); URL.revokeObjectURL(url); };
        a.play().catch(e => {
            console.warn("Playback failed:", e);
            if (onEnd) onEnd();
        });
    } catch (e) {
        console.error("playServerHex error", e);
        if (onEnd) onEnd();
    }
}

// UI: avatar glow & snico animation when speaking
function setInterviewerSpeaking(on) {
    if (on) avatarWrap.classList.add("avatar-active");
    else avatarWrap.classList.remove("avatar-active");
    // animate snico bars while speaking
    const bars = Array.from(document.querySelectorAll("#snico .bar"));
    if (!bars.length) return;
    if (on) {
        // ramp heights randomly while speaking
        const t = setInterval(() => {
            bars.forEach((b, i) => {
                const h = 12 + Math.round(Math.random() * (40 + (i % 3) * 10));
                b.style.height = h + "px";
            });
        }, 140);
        // store ref to cancel
        snico._talkingInterval = t;
    } else {
        if (snico._talkingInterval) { clearInterval(snico._talkingInterval); snico._talkingInterval = null; }
        // set muted small bars
        bars.forEach((b) => b.style.height = "8px");
    }
}

// UI: user mic meter and small snico movement while user speaks
function updateUserVisuals(level) {
    // level ~ [0..1]
    micFill.style.width = Math.min(100, Math.round(level * 100)) + "%";
    // subtle snico react
    const bars = Array.from(document.querySelectorAll("#snico .bar"));
    bars.forEach((b, idx) => {
        const x = Math.max(6, Math.round((level * 60) * (0.5 + ((idx % 3) / 3))));
        b.style.height = `${x}px`;
    });
}

// get media (camera+mic)
async function setupMedia() {
    if (masterStream) return;
    statusEl.textContent = "Requesting camera & mic permission…";
    try {
        masterStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: { width: 1280 } });
        videoEl.srcObject = masterStream;
        audioOnlyStream = new MediaStream(masterStream.getAudioTracks());
        statusEl.textContent = "Ready";
        initMeter(audioOnlyStream);
    } catch (e) {
        console.error("getUserMedia failed:", e);
        statusEl.textContent = "Allow camera & mic";
        alert("Please allow camera and microphone access for the interview to work.");
    }
}

// init meter (visualization)
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
            // smoothing
            rmsSmoothed = rmsSmoothed * 0.85 + rms * 0.15;
            updateUserVisuals(Math.min(1, rmsSmoothed * 4));
            requestAnimationFrame(drawMeter);
        })();
    } catch (e) {
        console.warn("initMeter error:", e);
    }
}

// calibrate ambient silence threshold (0.7s sampling)
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
                const rms = Math.sqrt(sum / data.length);
                samples.push(rms);
                if (performance.now() - start < 700) requestAnimationFrame(sample);
                else {
                    const avg = samples.reduce((s, x) => s + x, 0) / samples.length;
                    const thresh = Math.max(0.003, avg * 2.2); // a bit above ambient
                    try { ctx.close(); } catch (e) { }
                    resolve(thresh);
                }
            })();
        } catch (e) {
            console.warn("calibrateAmbient fallback", e);
            resolve(0.02);
        }
    });
}

// start the overall interview flow
async function startInterview() {
    statusEl.textContent = "Contacting server...";
    try {
        const res = await fetch(API_BASE + "/api/start", { method: "POST" });
        const j = await res.json();
        console.log("start response:", j);

        // If server returned interviewer audio, play it; avatar glows while playing
        const hex = j.ai_audio_b64 || j.ai_audio || null;
        setInterviewerSpeaking(false);
        playServerHex(hex,
            () => { setInterviewerSpeaking(true); statusEl.textContent = "Interviewer speaking…"; },
            async () => {
                setInterviewerSpeaking(false);
                statusEl.textContent = "Thinking (15s)…";
                // after interviewer audio ends, wait THINK then auto-record
                startThinkingTimer();
            }
        );
    } catch (e) {
        console.error("startInterview error", e);
        statusEl.textContent = "Server unreachable";
    }
}

// 15s think timer
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

// start auto-record: calibrate, record, watch silence
async function startRecordingAuto() {
    if (!audioOnlyStream) {
        console.warn("no audio stream — cannot record");
        statusEl.textContent = "No microphone";
        return;
    }

    // calibrate ambient
    statusEl.textContent = "Calibrating mic…";
    const threshold = await calibrateAmbient(audioOnlyStream);
    console.log("calibrated threshold:", threshold);
    silenceThreshold = threshold;

    // create recorder
    try {
        recorder = new MediaRecorder(audioOnlyStream, { mimeType: "audio/webm" });
    } catch (e) {
        recorder = new MediaRecorder(audioOnlyStream);
    }

    recordedChunks = [];
    recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) recordedChunks.push(ev.data); };
    recorder.onstop = onRecorderStop;

    recorder.start();
    isRecording = true;
    statusEl.textContent = "Recording… (max 90s)";
    // start silence monitor
    startSilenceMonitor(silenceThreshold);

    // enforce max answer length
    setTimeout(() => {
        if (isRecording) {
            console.log("max answer timeout reached -> stopping");
            stopRecordingAuto();
        }
    }, MAX_ANSWER_MS);
}

// silence monitor: if sustained silence for SILENCE_MS, stop recording
function startSilenceMonitor(threshold) {
    try {
        audioCtxSilence = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtxSilence.createMediaStreamSource(audioOnlyStream);
        analyserSilence = audioCtxSilence.createAnalyser();
        analyserSilence.fftSize = 2048;
        src.connect(analyserSilence);
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
            // small smoothing to avoid jitter
            rmsSmoothed = rmsSmoothed * 0.8 + rms * 0.2;

            // debug to console
            // console.log("silencePoll rms", rmsSmoothed, "threshold", threshold);

            // visual update already handled by meter
            if (rmsSmoothed < threshold) {
                if (!silenceStart) silenceStart = performance.now();
                else if (performance.now() - silenceStart >= SILENCE_MS) {
                    console.log("sustained silence -> stopping record");
                    stopRecordingAuto();
                    try { audioCtxSilence.close(); } catch (e) { }
                    return;
                }
            } else {
                silenceStart = null;
            }

            if (isRecording) requestAnimationFrame(poll);
        })();

    } catch (e) {
        console.warn("startSilenceMonitor error", e);
    }
}

function stopRecordingAuto() {
    if (!recorder || !isRecording) return;
    isRecording = false;
    try { if (recorder.state === "recording") recorder.stop(); } catch (e) { console.warn("stop recorder error", e); }
    statusEl.textContent = "Processing upload…";
}

// called when recorder stops: upload blob
async function onRecorderStop() {
    const blob = new Blob(recordedChunks, { type: recordedChunks[0]?.type || "audio/webm" });
    console.log("Recorded blob:", blob.size, blob.type);
    const fd = new FormData();
    fd.append("audio", blob, "answer.webm");

    try {
        statusEl.textContent = "Uploading…";
        const res = await fetch(API_BASE + "/api/send_audio", { method: "POST", body: fd });
        const j = await res.json();
        console.log("server /send_audio response:", j);

        // server returns ai_audio_b64 (hex) — play it
        const hex = j.ai_audio_b64 || j.ai_audio;
        // avatar glow while interviewer speaks
        playServerHex(hex,
            () => { setInterviewerSpeaking(true); statusEl.textContent = "Interviewer speaking…"; },
            () => {
                setInterviewerSpeaking(false);
                // continue: if agent expects more questions, schedule next thinking timer
                if (j.expect_more !== false) {
                    statusEl.textContent = "Thinking (15s)…";
                    startThinkingTimer();
                } else {
                    statusEl.textContent = "Interview complete.";
                }
            }
        );

    } catch (e) {
        console.error("upload/send_audio failed", e);
        statusEl.textContent = "Upload failed";
    } finally {
        // cleanup
        recordedChunks = [];
        try { if (audioCtxSilence) audioCtxSilence.close(); } catch (e) { }
    }
}

// end interview (manual)
endBtn.addEventListener("click", () => {
    // stop recording if active
    if (isRecording) stopRecordingAuto();
    statusEl.textContent = "Interview ended by user.";
    // optionally notify backend
    fetch(API_BASE + "/api/end", { method: "POST" }).catch(() => { });
});

// init on load
window.addEventListener("load", async () => {
    statusEl.textContent = "Starting…";
    await setupMedia();
    // allow UI to settle
    setTimeout(startInterview, 350);
});
