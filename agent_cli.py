# agent.py — Fixed, Edge-TTS (Neerja) safe speaker, Whisper STT, local Qwen LLM
import os
import time
import tempfile
import re
import random
import threading
import asyncio
import subprocess

import numpy as np
import sounddevice as sd
import soundfile as sf

# edge_tts for Neerja voice
import edge_tts
from playsound3 import playsound

import whisper
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# ----------------------------
# CONFIG
# ----------------------------
SILENCE_THRESHOLD = 0.01
SILENCE_DURATION = 6.0      # seconds of silence to stop
SAMPLE_RATE = 16000
BLOCKSIZE = 1024

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"  # local model
MAX_MAIN_QUESTIONS = 6
QUESTION_GEN_TOKENS = 64
FOLLOWUP_GEN_TOKENS = 64
FEEDBACK_GEN_TOKENS = 360

# ----------------------------
# EDGE TTS (Neerja)
# ----------------------------
EDGE_VOICE = "en-IN-NeerjaNeural"

async def _edge_synth(text: str, out_mp3: str):
    """Asynchronous edge_tts synth to save MP3 to out_mp3."""
    comm = edge_tts.Communicate(text, voice=EDGE_VOICE)
    await comm.save(out_mp3)

def run_async(coro_fn, *args, **kwargs):
    """
    Run coroutine safely even if an event loop is already running.
    If asyncio.run() works, use it. Otherwise run in a separate thread
    that executes asyncio.run() so caller blocks until completion.
    """
    try:
        # Try the simple path first
        return asyncio.run(coro_fn(*args, **kwargs))
    except RuntimeError:
        # event loop already running — use a thread to run asyncio.run there
        result_holder = {}

        def _target():
            try:
                result_holder['result'] = asyncio.run(coro_fn(*args, **kwargs))
            except Exception as e:
                result_holder['exc'] = e

        th = threading.Thread(target=_target)
        th.start()
        th.join()
        if 'exc' in result_holder:
            raise result_holder['exc']
        return result_holder.get('result')

def speak(text: str):
    """Synthesize text with edge-tts (Neerja), play it, cleanup. Blocks until playback done."""
    text = (text or "").strip()
    if not text:
        return

    mp3_path = tempfile.mktemp(suffix=".mp3")

    try:
        # 1) synthesize mp3 file (edge-tts)
        run_async(_edge_synth, text, mp3_path)

        # 2) play mp3 (playsound3 is simple and worked for you before)
        #    playsound blocks until finished.
        playsound(mp3_path)

    except Exception as e:
        print("TTS error:", e)
        # fallback to console output so the user still sees prompt
        print("AI:", text)
    finally:
        # 3) cleanup temporary mp3
        try:
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
        except Exception:
            pass

    # small pause to avoid immediate mic grabbing
    time.sleep(0.18)


# ----------------------------
# RECORD UNTIL SILENCE
# ----------------------------
def record_until_silence(filename="input.wav", timeout=90):
    """
    Record from default input until SILENCE_DURATION of near-silence
    or until timeout. Writes to `filename` and returns it.
    """
    print("Listening... (speak now)")
    rec = []
    silence_start = None
    start_time = time.time()

    def callback(indata, frames, time_info, status):
        # copy because sounddevice reuses the buffer
        rec.append(indata.copy())

    try:
        with sd.InputStream(channels=1, samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, callback=callback):
            while True:
                time.sleep(0.05)
                if not rec:
                    continue

                n_blocks = max(1, int(0.5 * SAMPLE_RATE / BLOCKSIZE))
                recent = np.concatenate(rec[-n_blocks:], axis=0)
                rms = np.sqrt(np.mean(recent.astype(np.float32) ** 2))

                if rms < SILENCE_THRESHOLD:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= SILENCE_DURATION:
                        break
                else:
                    silence_start = None

                if time.time() - start_time > timeout:
                    print("Recording timeout reached.")
                    break
    except Exception as e:
        print("Microphone / InputStream error:", e)
        # write a very short silent file to avoid later crashes
        sf.write(filename, np.zeros((1600,1), dtype=np.float32), SAMPLE_RATE)
        return filename

    if not rec:
        # nothing recorded, save a tiny silent file
        sf.write(filename, np.zeros((1600,1), dtype=np.float32), SAMPLE_RATE)
        print("No audio captured; wrote silent file.")
        return filename

    audio = np.concatenate(rec, axis=0)
    sf.write(filename, audio, SAMPLE_RATE)
    print("Saved recording:", filename)
    return filename


# ----------------------------
# Whisper STT
# ----------------------------
print("Loading Whisper-small...")
whisper_model = whisper.load_model("small")

def transcribe(path):
    print("Transcribing...")
    try:
        res = whisper_model.transcribe(path)
        return res.get("text", "").strip()
    except Exception as e:
        print("Whisper transcribe error:", e)
        return ""


# ----------------------------
# Local LLM (Qwen)
# ----------------------------
print("Loading Qwen2.5-3B-Instruct (CPU)...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, torch_dtype=torch.float32, device_map=None)
model.eval()
print("Qwen loaded.")

def generate_llm_guarded(prompt, max_new_tokens=128, temperature=0.22, retries=2, require_question=False):
    """
    Generate text but return only generated tokens (no echo).
    If require_question=True, ensure the output contains at least one '?'.
    Retries a couple times with slight prompt tweaks if not valid.
    """
    for attempt in range(retries):
        inputs = tokenizer(prompt, return_tensors="pt")
        input_len = inputs["input_ids"].shape[1]
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )
        gen_ids = out[0][input_len:]
        text = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
        lines = [l.strip() for l in re.split(r'[\n\r]+', text) if l.strip()]
        if require_question:
            q_lines = [l for l in lines if '?' in l and len(l) < 250]
            if q_lines:
                return q_lines[0]
            # tweak prompt and retry
            prompt = prompt + "\nPlease respond with only a single concise question sentence (end with '?')."
            continue
        return lines[0] if lines else text
    return ""


# ----------------------------
# Role banks (unchanged)
# ----------------------------
ROLE_BANK = {
    "software": [
        "Describe how a hash table works and an example use-case.",
        "What is the time complexity of searching in a balanced BST?",
        "Explain how to reverse a singly linked list (describe steps).",
        "Difference between stack and queue with an example.",
        "How does HTTPS differ from HTTP in basic terms?",
        "Given an array, how to find longest subarray with sum zero? Outline approach.",
        "How to detect cycles in a directed graph?"
    ],
    "analytics": [
        "What is mean vs median and when to use each?",
        "How do you handle missing values: name two methods.",
        "Write a simple SQL query to find total sales per month.",
        "What is a p-value in one sentence?",
        "How to design a basic A/B test and check significance?"
    ],
    "custom": [
        "Tell me briefly what areas you want to practice."
    ]
}

ROLE_KEYS = {
    "software": ["software","developer","engineer","backend","frontend","fullstack","swe","programmer","development"],
    "analytics": ["analytics","analyst","data","business intelligence","bi","data analyst"],
    "custom": []
}

def map_role_to_key(role_text):
    rt = (role_text or "").lower()
    for key,kws in ROLE_KEYS.items():
        for kw in kws:
            if kw in rt:
                return key
    if "data" in rt:
        return "analytics"
    return "custom"

def extract_role(sentence):
    s = (sentence or "").strip().lower()
    patterns = [
        r"role of (.+)",
        r"role as (.+)",
        r"for the (.+) role",
        r"for (?:a|an|the)?\s*(.+?)\s*(?:role|position)?[.?!]*$",
        r"i want to practice (?:for|as)\s*(.+)[.?!]*$",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            candidate = m.group(1).strip()
            candidate = re.sub(r"\b(role|position|job|please)\b", "", candidate).strip()
            return " ".join(candidate.split()[:6])
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", s)]
    if not words:
        return "software developer"
    if len(words) <= 3:
        return " ".join(words)
    return " ".join(words[-3:])

def detect_user_type_final(transcript):
    text = (transcript or "").lower()
    words = len(text.split())
    if words < 50:
        return "Efficient"
    if words > 400:
        return "Chatty"
    if "don't know" in text or "not sure" in text:
        return "Confused"
    return "Efficient"


# ----------------------------
# Interview flow prompts
# ----------------------------
SYSTEM_Q_PROMPT = ("You are a concise professional interviewer for fresh graduates. "
                   "Respond with ONLY a single question sentence (no extra text).")

SYSTEM_FU_PROMPT = ("You are a concise professional interviewer. "
                    "Produce ONLY a single follow-up question sentence that requests a missing specific detail related to the user's answer. "
                    "Do NOT repeat the user's words; ask for a concrete metric, method, small example, complexity, or clarification.")

def sanitize_question(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(r'^(Question[:\-]*\s*)','', q, flags=re.I)
    if not q.endswith('?'):
        q = q.rstrip('.').rstrip() + '?'
    return q


# ----------------------------
# Main
# ----------------------------
def main():
    try:
        greet = "Hello — I am your interview practice partner. Which role would you like to practice for?"
        print("AI:", greet)
        speak(greet)

        # role capture
        rpath = record_until_silence("role.wav", timeout=30)
        role_sentence = transcribe(rpath)
        print("Transcribed role sentence:", role_sentence)
        role_name = extract_role(role_sentence)
        role_key = map_role_to_key(role_name)
        print(f"Selected role: '{role_name}' -> {role_key}")
        speak(f"Great. We'll practice for the {role_name} role. I'll ask a few focused questions.")

        bank = ROLE_BANK.get(role_key, ROLE_BANK["custom"])
        qpool = list(bank)
        random.shuffle(qpool)
        questions = qpool[:MAX_MAIN_QUESTIONS]

        history = []
        for idx, base in enumerate(questions, start=1):
            q_prompt = SYSTEM_Q_PROMPT + f"\nBase: {base}\nRole: {role_name}\nRespond with ONLY one clear question sentence."
            q_text = generate_llm_guarded(q_prompt, max_new_tokens=QUESTION_GEN_TOKENS, temperature=0.18, retries=2, require_question=True)
            if not q_text:
                q_text = base
            q_text = sanitize_question(q_text)
            print(f"\nAI (Q{idx}):", q_text)
            speak(q_text)
            history.append(("assistant", q_text))

            a_path = record_until_silence(f"answer_{idx}.wav", timeout=90)
            a_text = transcribe(a_path)
            print("You:", a_text)
            history.append(("user", a_text))

            fu_prompt = SYSTEM_FU_PROMPT + f"\nUserAnswer:\n\"\"\"\n{a_text}\n\"\"\"\nRole: {role_name}\nInstruction: Ask a single concise follow-up for a missing specific detail."
            fu_text = generate_llm_guarded(fu_prompt, max_new_tokens=FOLLOWUP_GEN_TOKENS, temperature=0.18, retries=2, require_question=True)
            if not fu_text or "NO_FOLLOWUP" in (fu_text or "").upper():
                fallback = {
                    "software":"Can you give the time and space complexity of your approach?",
                    "analytics":"Which metric would you track to verify this change worked?",
                    "custom":"Can you clarify which detail I should probe?"
                }
                fu_text = fallback.get(role_key, "Can you clarify one concrete metric or example?")
            fu_text = sanitize_question(fu_text)
            print("AI (follow-up):", fu_text)
            speak(fu_text)
            history.append(("assistant", fu_text))

            fu_path = record_until_silence(f"fu_{idx}.wav", timeout=60)
            fu_ans = transcribe(fu_path)
            print("You (follow-up):", fu_ans)
            history.append(("user", fu_ans))

        transcript_all = "\n".join([f"{r}: {t}" for r,t in history])
        user_type = detect_user_type_final(transcript_all)
        print("\nAI: Generating final feedback...")
        speak("Generating your final feedback now.")

        fb_prompt = (f"You are a professional interviewer. Role: {role_name}. Candidate transcript:\n{transcript_all}\n\n"
                     "Provide structured feedback with numeric scores (0-10) for: Communication, Role Knowledge, Problem Solving, Conciseness. "
                     "Give 3 concrete improvement suggestions and one concise improved example answer for the weakest point. "
                     f"Also summarize the candidate type as one of: Confused, Efficient, Chatty, Edge-case. Candidate type: {user_type}.\n"
                     "Respond professionally, do NOT include any meta or labels besides the requested items.")
        feedback = generate_llm_guarded(fb_prompt, max_new_tokens=FEEDBACK_GEN_TOKENS, temperature=0.2, retries=2, require_question=False)
        print("\n=== FEEDBACK ===\n")
        print(feedback)
        speak("Here is your final feedback. " + feedback)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print("Error during interview:", e)


if __name__ == "__main__":
    main()
