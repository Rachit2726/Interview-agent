# backend/tts_engine.py
import tempfile
import os
import threading
import asyncio
import edge_tts
from typing import Optional

EDGE_VOICE = "en-IN-NeerjaNeural"

async def _edge_synth(text: str, out: str):
    comm = edge_tts.Communicate(text, voice=EDGE_VOICE)
    await comm.save(out)

def run_async(coro_fn, *args, **kwargs):
    """
    Run coroutine safely even if an asyncio loop is already running.
    If not running, this just calls asyncio.run.
    If a loop is running, it runs asyncio.run in a separate thread and returns when done.
    """
    try:
        return asyncio.run(coro_fn(*args, **kwargs))
    except RuntimeError:
        # event loop already running in this thread — run in a thread
        result = {}
        def _target():
            try:
                result['res'] = asyncio.run(coro_fn(*args, **kwargs))
            except Exception as e:
                result['exc'] = e
        th = threading.Thread(target=_target)
        th.start()
        th.join()
        if 'exc' in result:
            raise result['exc']
        return result.get('res')

def synthesize_mp3_bytes(text: str) -> bytes:
    """
    Synthesize TTS to MP3, return bytes. Caller can hex() it for JSON transport.
    """
    text = (text or "").strip()
    if not text:
        return b""
    out_mp3 = tempfile.mktemp(suffix=".mp3")
    try:
        # synthesize (blocking; safe for running event loop)
        run_async(_edge_synth, text, out_mp3)
        with open(out_mp3, "rb") as f:
            data = f.read()
        return data
    finally:
        try:
            if os.path.exists(out_mp3):
                os.remove(out_mp3)
        except:
            pass
