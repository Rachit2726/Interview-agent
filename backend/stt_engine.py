# backend/stt_engine.py
import whisper
import os

print("Loading Whisper (backend)...")
_whisper = whisper.load_model("small")   # uses config.WHISPER_MODEL if you prefer

def transcribe_file(path: str) -> str:
    try:
        res = _whisper.transcribe(path)
        text = res.get("text", "").strip()
        print("=== Whisper Transcription ===")
        print(text)
        print("=============================")
        return text
    except Exception as e:
        print("Whisper transcribe error:", e)
        return ""
