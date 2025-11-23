# backend/agent.py
import random
import re
from llm_engine import ask_llm
from tts_engine import synthesize_mp3_bytes
from config import MAX_QUESTIONS

# Role bank extended (8 roles)
ROLE_BANK = {
    "software": [
        "Explain how a hash table works.",
        "What is the time complexity of searching in a balanced BST?",
        "Explain how to reverse a singly linked list.",
        "How to detect cycles in a directed graph?",
        "Describe a time you debugged a tricky bug.",
        "What is the difference between process and thread?"
    ],
    "analytics": [
        "Explain mean vs median.",
        "How do you handle missing values?",
        "Write a SQL query to get total sales per month.",
        "How would you A/B test a website change?",
        "Which metric would you pick for retention?",
        "Explain bias vs variance."
    ],
    "sales": [
        "How do you open a conversation with a cold lead?",
        "Explain a time you closed a deal.",
        "How do you handle 'too expensive' objection?"
    ],
    "product": [
        "How would you decide MVP scope for a new feature?",
        "How to prioritize features with a small data set?"
    ],
    "design": [
        "What is a user persona?",
        "How would you validate a navigation change quickly?"
    ],
    "ml": [
        "What is overfitting and how do you avoid it?",
        "Explain confusion matrix metrics."
    ],
    "hr": [
        "What qualities do you look for in a new graduate?",
        "How do you give quick constructive feedback?"
    ],
    "custom": ["Tell me briefly what areas you want to practice."]
}

def match_role_text(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["soft", "dev", "engineer"]):
        return "software"
    if any(k in t for k in ["data", "analyst"]):
        return "analytics"
    if any(k in t for k in ["sales", "business development", "bd"]):
        return "sales"
    if any(k in t for k in ["product", "pm", "product manager"]):
        return "product"
    if any(k in t for k in ["design", "ux", "ui"]):
        return "design"
    if any(k in t for k in ["ml", "machine learning", "ai"]):
        return "ml"
    if any(k in t for k in ["hr", "people", "talent"]):
        return "hr"
    return "custom"

def _is_gibberish(text: str) -> bool:
    if not text:
        return True
    txt = text.strip()
    # too short
    if len(txt) < 3:
        return True
    # too many non-letter characters
    non_alpha = sum(1 for c in txt if not (c.isalpha() or c.isspace()))
    if non_alpha / max(1, len(txt)) > 0.25:
        return True
    # repeated short tokens (like "ʕ ʕ ʔ") or nonsense
    if re.fullmatch(r'[^A-Za-z0-9\s]{2,}', txt):
        return True
    return False

class InterviewAgent:
    def __init__(self):
        self.role_name = None
        self.role_key = None
        self.questions = []
        self.history = []     # list of tuples (speaker, text)
        self.q_index = 0
        self.state = "idle"

    def start(self):
        self.state = "await_role"
        text = "Hello, I am your interview partner. Which role would you like to practice?"
        mp3 = synthesize_mp3_bytes(text)
        return {"ai_text": text, "ai_audio_b64": mp3.hex() if mp3 else None}

    def process_audio_text(self, text: str):
        text = (text or "").strip()
        print("Agent received text:", text)
        if _is_gibberish(text):
            # ask user to repeat once, do not assume anything
            self.state = "await_role" if self.state == "idle" else self.state
            reply = "I didn't catch that — could you please repeat briefly?"
            mp3 = synthesize_mp3_bytes(reply)
            return {"ai_text": reply, "ai_audio_b64": mp3.hex() if mp3 else None}

        if self.state == "await_role":
            self.role_name = text
            self.role_key = match_role_text(text)
            bank = ROLE_BANK.get(self.role_key, ROLE_BANK["custom"])
            # fix to exactly MAX_QUESTIONS, repeatable deterministic shuffle
            random.shuffle(bank)
            self.questions = bank[:MAX_QUESTIONS]
            self.q_index = 0
            self.state = "ask_q"
            return self.ask_question()

        if self.state == "await_answer":
            # store user's answer
            self.history.append(("user", text))
            # generate one focused follow-up that requests a missing, measurable detail
            fu_prompt = (
                f"Candidate answer: {text}\n"
                "You are an interviewer. Generate exactly one concise follow-up question "
                "that requests a single missing specific detail (example: metric, complexity, time, version, example). "
                "Do NOT repeat the user's words; ask precisely and concisely."
            )
            fu = ask_llm(fu_prompt, max_new_tokens=60, require_question=True)
            fu = fu.strip()
            if not fu:
                fu = "Can you provide one concrete example or a metric for that?"
            self.history.append(("assistant", fu))
            self.state = "await_followup"
            mp3 = synthesize_mp3_bytes(fu)
            return {"ai_text": fu, "ai_audio_b64": mp3.hex() if mp3 else None}

        if self.state == "await_followup":
            # record follow-up answer
            self.history.append(("user", text))
            self.q_index += 1
            if self.q_index >= len(self.questions):
                return self.final_feedback()
            return self.ask_question()

        # fallback
        self.state = "await_role"
        text = "Which role would you like to practice?"
        mp3 = synthesize_mp3_bytes(text)
        return {"ai_text": text, "ai_audio_b64": mp3.hex() if mp3 else None}

    def ask_question(self):
        # ensure index valid
        if not self.questions or self.q_index >= len(self.questions):
            # no questions left → final feedback
            return self.final_feedback()
        base = self.questions[self.q_index]
        q_prompt = f"Turn into one crisp interview question for a fresher: {base}"
        q = ask_llm(q_prompt, max_new_tokens=60, require_question=True)
        q = q.strip()
        if not q:
            q = base if base.endswith('?') else base.rstrip('.') + '?'
        self.history.append(("assistant", q))
        self.state = "await_answer"
        mp3 = synthesize_mp3_bytes(q)
        return {"ai_text": q, "ai_audio_b64": mp3.hex() if mp3 else None}

    def final_feedback(self):
        # Build transcript
        transcript = "\n".join([f"{s}: {t}" for s, t in self.history])

        # --- Detect user type ---
        user_msgs = [t for s, t in self.history if s == "user"]
        joined = " ".join(user_msgs).lower()

        # Heuristics
        confused = (
            any(k in joined for k in ["i don't know", "not sure", "no idea", "what do you mean"]) or
            len(user_msgs) <= 1
        )

        efficient = (
            all(len(msg.split()) <= 12 for msg in user_msgs) and
            not confused
        )

        chatty = (
            any(len(msg.split()) >= 40 for msg in user_msgs) and
            not confused
        )

        edgecase = (
            any(len(re.findall(r"[^a-zA-Z0-9\s]", msg)) > 5 for msg in user_msgs) or
            any(len(msg.split()) <= 2 for msg in user_msgs)
        )

        # Select user type
        if edgecase:
            user_type = "Edge-case User"
            reason = "Provided input that was irrelevant, invalid, or contained unexpected characters."
        elif confused:
            user_type = "Confused User"
            reason = "Showed uncertainty or difficulty understanding what they wanted to practice."
        elif chatty:
            user_type = "Chatty User"
            reason = "Gave long, detailed, sometimes off-topic explanations."
        elif efficient:
            user_type = "Efficient User"
            reason = "Gave short, direct answers and moved quickly through the interview."
        else:
            user_type = "General User"
            reason = "Answered normally without any strong behavioral pattern."

        # --- LLM Feedback Prompt ---
        fb_prompt = (
            "You are an experienced interviewer. Given the transcript below, produce structured feedback. "
            "Return EXACTLY this format (no extra lines):\n"
            "Communication (0-10): <score>\n"
            "Role Knowledge (0-10): <score>\n"
            "Problem Solving (0-10): <score>\n"
            "Conciseness (0-10): <score>\n"
            "3 Improvements:\n- x\n- y\n- z\n"
            "Improved example answer (one paragraph):\n\n"
            f"Transcript:\n{transcript}"
        )

        fb = ask_llm(fb_prompt, max_new_tokens=240)

        # Append user type at the end
        fb += f"\n\nUser Type: {user_type}\nReason: {reason}"

        # Give TTS
        mp3 = synthesize_mp3_bytes("Here is your final feedback. " + fb)
        self.state = "done"

        return {
            "ai_text": fb,
            "ai_audio_b64": mp3.hex() if mp3 else None
        }
