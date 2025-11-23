# backend/main.py
import os
import tempfile
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from agent import InterviewAgent
from stt_engine import transcribe_file

app = FastAPI()
agent = InterviewAgent()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.post("/api/start")
def start():
    return agent.start()

@app.post("/api/send_audio")
async def send_audio(audio: UploadFile = File(...)):
    print("\n\n==============================")
    print("=== /api/send_audio CALLED ===")
    print("==============================")

    suffix = os.path.splitext(audio.filename)[1] or ".webm"
    tmp_path = tempfile.mktemp(suffix=suffix)
    data = await audio.read()
    with open(tmp_path, "wb") as f:
        f.write(data)

    print(f"Saved incoming audio -> {tmp_path}")
    print("File size:", len(data), "bytes")

    # transcribe
    text = transcribe_file(tmp_path)

    try:
        os.remove(tmp_path)
    except:
        pass

    # pass to agent
    try:
        result = agent.process_audio_text(text)
    except Exception as e:
        print("Agent processing error:", e)
        # reset agent and restart flow
        result = agent.start()

    # return user_text + agent reply
    res = {"user_text": text}
    if isinstance(result, dict):
        res.update(result)
    else:
        res["ai_text"] = str(result)
    return res
