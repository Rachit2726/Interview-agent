# backend/llm_engine.py
import torch
import re
from transformers import AutoTokenizer, AutoModelForCausalLM
from config import MODEL_NAME

print("Loading Qwen (backend)...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, torch_dtype=torch.float32)
model.eval()
print("Qwen ready (backend).")

# Strong system persona for interviewer
SYSTEM_PROMPT = (
    "You are a concise, professional interviewer for junior candidates. "
    "Always produce ONE short output only. If asking a question, produce exactly one question sentence and nothing else. "
    "Do NOT include meta commentary, greetings, or numbered lists. Keep language simple and direct."
)

def _clean_output(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    # Remove common prefaces like "Sure", "Here is", "AI:", "Assistant:"
    s = re.sub(r'^(Sure[,.:]?\s*|Here (is|are)[,:]?\s*|AI:|Assistant:)\s*', '', s, flags=re.I)
    # Trim trailing instruction leakage
    s = re.sub(r'\s*(Please respond.*)$', '', s, flags=re.I)
    s = s.strip()
    return s

def _extract_first_question(text: str) -> str:
    # Find the first sentence that contains a '?'
    # fallback: if no '?', turn the first short sentence into a question
    lines = [ln.strip() for ln in re.split(r'[\r\n]+', text) if ln.strip()]
    for ln in lines:
        if '?' in ln:
            # return shortest question-like substring
            m = re.search(r'([^\?]{5,250}\?)', ln)
            if m:
                return m.group(1).strip()
            return ln
    # no question found — try to craft a single short question from text
    first = lines[0] if lines else text
    first = re.sub(r'\.$', '?', first)
    if not first.endswith('?'):
        first = first.rstrip('.') + '?'
    return first

def ask_llm(prompt: str, max_new_tokens: int = 128, require_question: bool = False) -> str:
    full_prompt = SYSTEM_PROMPT + "\n\n" + prompt
    inputs = tokenizer(full_prompt, return_tensors="pt")
    ilen = inputs["input_ids"].shape[1]
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id
        )
    raw = tokenizer.decode(out[0][ilen:], skip_special_tokens=True).strip()
    cleaned = _clean_output(raw)
    if require_question:
        q = _extract_first_question(cleaned)
        return q
    return cleaned
