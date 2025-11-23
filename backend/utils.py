# backend/utils.py
import re
import random

ROLE_BANK = {
    "software": [
        "Explain time complexity of searching in a balanced BST.",
        "Describe how a hash table works and an example use-case.",
        "Explain how to reverse a singly linked list in-place.",
        "How would you detect cycles in a directed graph?"
    ],
    "analytics": [
        "What's the difference between mean and median, and when to use each?",
        "How would you handle missing values in a dataset?",
        "Write a simple SQL query to compute total sales per month."
    ],
    "retail": [
        "How would you handle an upset customer in a store?",
        "Describe how you'd upsell while respecting customer needs.",
        "What metrics would you track in a retail store?"
    ],
    "sales": [
        "How do you open a conversation with a cold lead?",
        "How would you handle the objection 'too expensive'?",
        "Describe a time you closed a difficult sale (behavioural)."
    ],
    "product": [
        "How do you decide MVP features for a new product?",
        "Name one metric for onboarding success and why.",
        "How would you collect rapid user feedback?"
    ],
    "hr": [
        "What qualities do you look for in a new graduate hire?",
        "How do you give constructive feedback to an underperforming employee?",
        "How would you design a fair interview process?"
    ],
    "support": [
        "How do you prioritize support tickets?",
        "How would you explain a technical fix to a non-technical customer?",
        "Describe a time you handled a difficult support case."
    ],
    "marketing": [
        "How do you measure the success of a digital campaign?",
        "Describe an audience segmentation approach for a product.",
        "Give one low-cost marketing channel and why it works."
    ],
    "custom": ["Tell me briefly what areas you want to practice."]
}

def pick_questions(bank: list, n: int):
    return random.sample(bank, min(n, len(bank)))

def match_role_text(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["soft", "dev", "engineer", "backend", "frontend", "programmer"]):
        return "software"
    if any(k in t for k in ["data", "analyst", "analytics"]):
        return "analytics"
    if "retail" in t:
        return "retail"
    if "sales" in t or "bd " in t:
        return "sales"
    if "product" in t or "pm" in t:
        return "product"
    if "hr" in t:
        return "hr"
    if "support" in t or "customer" in t:
        return "support"
    if "marketing" in t:
        return "marketing"
    return "custom"
