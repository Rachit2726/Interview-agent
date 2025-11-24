from llm_engine import ask_llm
from tts_engine import synthesize_mp3_bytes
from config import MAX_QUESTIONS
import random

ROLE_BANK = {
    "software": [
        "Explain how a hash table works.",
        "What is the time complexity of searching in a balanced BST?",
        "Explain how to reverse a singly linked list.",
        "How to detect cycles in a directed graph?"
    ],
    "analytics": [
        "What is mean vs median?",
        "How to handle missing values?",
        "Write a SQL query for total sales per month."
    ],
    "sales": [
        "Explain how you would handle an objection from a customer.",
        "What is your approach to closing a high-value deal?",
        "Describe how you qualify a lead."
    ],
    "retail": [
        "How would you handle an angry customer?",
        "What steps do you take to ensure correct billing?",
        "How do you manage store inventory accurately?"
    ],
    "product": [
        "What is a product roadmap?",
        "How do you prioritize features?",
        "Explain MVP in product development."
    ],
    "support": [
        "How do you communicate with a frustrated customer?",
        "Explain your escalation strategy.",
        "How do you handle repeated complaints?"
    ],
    "hr": [
        "How do you conduct a candidate screening?",
        "Explain structured interview vs unstructured interview.",
        "How do you evaluate culture fit?"
    ],
    "marketing": [
        "Explain the basics of a marketing funnel.",
        "How do you measure campaign success?",
        "Describe your approach to customer segmentation."
    ],
    "custom": ["Tell me what area you want to practice."]
}

def match_role_text(text: str):
    t = (text or "").lower()

    if any(x in t for x in ["soft", "dev", "engineer"]): return "software"
    if any(x in t for x in ["data", "analyst"]): return "analytics"
    if "sales" in t: return "sales"
    if "retail" in t: return "retail"
    if "product" in t: return "product"
    if "support" in t or "customer" in t: return "support"
    if "hr" in t or "human" in t: return "hr"
    if "market" in t or "growth" in t: return "marketing"

    return "custom"


class InterviewAgent:
    def __init__(self):
        self.state = "idle"
        self.role_key = None
        self.questions = []
        self.q_index = 0
        self.history = []


    def start(self):
        self.state = "await_role"
        text = "Hello, I am your interview partner. Which role would you like to practice?"
        mp3 = synthesize_mp3_bytes(text)
        return {
            "ai_text": text,
            "ai_audio_b64": mp3.hex(),
            "expect_more": True
        }


    def process_audio_text(self, text: str):
        text = (text or "").strip()
        print("Agent received text:", text)

        # ---------------- ROLE SELECTION ----------------
        if self.state == "await_role":
            self.role_key = match_role_text(text)
            bank = ROLE_BANK[self.role_key]

            # pick 3 random questions
            self.questions = random.sample(bank, min(MAX_QUESTIONS, len(bank)))
            self.q_index = 0
            self.state = "ask_q"

            return self.ask_question()


        # ---------------- FIRST ANSWER TO MAIN QUESTION ----------------
        if self.state == "await_answer":
            self.history.append(("user", text))
            return self.generate_followup(text)


        # ---------------- ANSWER TO FOLLOWUP ----------------
        if self.state == "await_followup":
            self.history.append(("user", text))
            self.q_index += 1

            if self.q_index >= len(self.questions):
                return self.final_feedback()

            return self.ask_question()

        # fallback
        return self.start()



    # ===================== ASK QUESTION =====================
    def ask_question(self):
        q_raw = self.questions[self.q_index]

        prompt = f"""
Turn the following into a single crisp interview question.
Rules:
- No examples.
- No explanations.
- No rephrasing meta-text.
- Only output the question itself.

Question: {q_raw}
"""

        q_clean = ask_llm(prompt, max_new_tokens=50)
        self.history.append(("assistant", q_clean))

        mp3 = synthesize_mp3_bytes(q_clean)
        self.state = "await_answer"

        return {
            "ai_text": q_clean,
            "ai_audio_b64": mp3.hex(),
            "expect_more": True
        }



    # ===================== FOLLOW-UP =====================
    def generate_followup(self, user_answer):
        prompt = f"""
You are an interviewer. Generate ONE follow-up question ONLY if needed.

Rules:
- Must ask for a missing technical detail *related to the question asked*.
- Do NOT ask behavioral questions like "challenges you faced".
- Do NOT ask meta-questions like "could you elaborate more".
- Follow-up must be specific and technical.
- If user answer is already complete, ask a clarifying detail.
- Do NOT output anything except the question.

User answer: {user_answer}
"""

        followup = ask_llm(prompt, max_new_tokens=50)

        self.history.append(("assistant", followup))
        mp3 = synthesize_mp3_bytes(followup)

        self.state = "await_followup"

        return {
            "ai_text": followup,
            "ai_audio_b64": mp3.hex(),
            "expect_more": True
        }



    # ===================== FINAL FEEDBACK =====================
    def final_feedback(self):
        transcript = "\n".join([f"{r}: {t}" for r, t in self.history])

        # Determine user type
        type_prompt = f"""
Based on this interview transcript, classify the user as exactly one of:
- Confused
- Efficient
- Chatty
- Edge-case

Transcript: {transcript}

Answer ONLY the type name.
"""
        user_type = ask_llm(type_prompt)



        fb_prompt = f"""
Give final interview feedback based on this transcript.

Transcript:
{transcript}

Include:
- Communication score
- Role knowledge score
- Technical depth score
- Conciseness score
- Strengths
- Areas for improvement
- Final classification: {user_type}
"""

        feedback = ask_llm(fb_prompt, max_new_tokens=220)
        mp3 = synthesize_mp3_bytes(feedback)

        self.state = "done"

        return {
            "ai_text": feedback,
            "ai_audio_b64": mp3.hex(),
            "expect_more": False     # ❗ Tells frontend to STOP
        }
