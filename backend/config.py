# backend/config.py
MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
WHISPER_MODEL = "small"               # whisper model id used by whisper.load_model
EDGE_VOICE = "en-IN-NeerjaNeural"     # chosen Neerja voice

# audio / recording
SAMPLE_RATE = 16000
BLOCKSIZE = 1024

# interview config
MAX_QUESTIONS = 3        # fixed to 3 questions per session
SILENCE_DURATION = 6.0   # stop after 6 seconds of sustained silence
TIMEOUT = 90             # max recording per answer in seconds
