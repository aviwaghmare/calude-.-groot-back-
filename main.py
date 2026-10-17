"""
Groot chatbot backend  (FastAPI + RapidFuzz)

HOW THE "BRAIN" WORKS (no LLM, only your data.json):
  1. EXACT       -> the cleaned question already exists in data.json
  2. SPELLING    -> every unknown word is replaced by the closest known word
                    ("whoo" -> "who"), then we check for an exact match again
  3. CLOSEST     -> compare against every stored question, take the best score
  4. If the best score is below MIN_SCORE (default 50%), we say "not understood".

SETTINGS (set in the Render dashboard -> Environment):
  MIN_SCORE        minimum match percentage, e.g. 45 or 60
  ALLOWED_ORIGINS  comma separated list, e.g. https://yourname.github.io
                   (use * while testing)

RUN LOCALLY:
  pip install -r requirements.txt
  uvicorn main:app --reload        -> http://127.0.0.1:8000/docs
"""
import json
import os
import random
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

MIN_SCORE = float(os.getenv("MIN_SCORE", "50"))
ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

DATA = json.loads((Path(__file__).parent / "data.json").read_text(encoding="utf-8"))


SLANG = {"ur": "your", "u": "you", "wat": "what", "abt": "about", "wht": "what", "pls": "please"}


def clean(text: str) -> str:
    """lowercase, remove punctuation, expand slang, collapse spaces"""
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return " ".join(SLANG.get(w, w) for w in text.split())


# every question variant -> index of its entry in DATA
PAIRS = [(clean(q), i) for i, e in enumerate(DATA) for q in e["q"]]
QUESTIONS = [q for q, _ in PAIRS]
EXACT = dict(PAIRS)
VOCAB = sorted({w for q in QUESTIONS for w in q.split()})
VOCAB_SET = set(VOCAB)


def fix_spelling(text: str) -> str:
    """replace unknown words by the most similar known word (edit-distance based)"""
    out = []
    for w in text.split():
        if w in VOCAB_SET or len(w) < 3 or w.isdigit():
            out.append(w)
            continue
        hit = process.extractOne(w, VOCAB, scorer=fuzz.ratio, score_cutoff=70)
        out.append(hit[0] if hit else w)
    return " ".join(out)


STOP = set("a an the is are was were am do does did you your ur u me my i of to in on at about "
           "tell what who whom whose which when where why how can could would please".split())


def content(text: str) -> str:
    """keep only the meaningful words ("tell me about infinity war" -> "infinity war")"""
    return " ".join(w for w in text.split() if w not in STOP)


def similarity(a: str, b: str, **_) -> float:
    """0-100 score: half looks at the full sentence, half at the meaningful words only.
    Tweak the weights to tune accuracy."""
    full = 0.7 * fuzz.token_sort_ratio(a, b) + 0.3 * fuzz.token_set_ratio(a, b)
    ca, cb = content(a), content(b)
    if not ca or not cb:
        return full
    return 0.5 * full + 0.5 * fuzz.token_sort_ratio(ca, cb)


NOT_UNDERSTOOD = [
    "I am Groot? (Rocket says: I didn’t get that one. Try asking about the Guardians, my powers or my friends.)",
    "I am Groot… (That’s outside my roots. Ask me about my story, Rocket or the movies.)",
]
SAMPLES = ["Who are the Guardians of the Galaxy?", "What are your powers?", "Who is Rocket?",
           "What happened in Infinity War?", "What do you eat?", "Why do you protect your friends?"]

app = FastAPI(title="Groot Chatbot API")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=300)


@app.get("/")
@app.get("/health")
def health():
    # the frontend calls this first to wake up the sleeping free Render server
    return {"status": "awake", "questions_known": len(QUESTIONS)}


@app.post("/chat")
def chat(body: ChatIn):
    cleaned = clean(body.message)
    if not cleaned:
        return {"matched": False, "answer": random.choice(NOT_UNDERSTOOD), "score": 0,
                "stage": "empty", "understood_as": "", "suggestions": random.sample(SAMPLES, 3)}

    # STEP 1: exact question exists
    if cleaned in EXACT:
        return reply(EXACT[cleaned], 100, "exact", cleaned, cleaned)

    # STEP 2: fix spelling, then try exact again
    fixed = fix_spelling(cleaned)
    if fixed in EXACT:
        return reply(EXACT[fixed], 100, "spelling", fixed, cleaned)

    # STEP 3: most similar stored question, must pass the minimum score
    best = process.extractOne(fixed, QUESTIONS, scorer=similarity)
    if best and best[1] >= MIN_SCORE:
        return reply(PAIRS[best[2]][1], round(best[1]), "closest", best[0], cleaned)

    print(f"UNANSWERED: {body.message!r}")  # visible in Render logs: add these to data.json later
    return {"matched": False, "answer": random.choice(NOT_UNDERSTOOD),
            "score": round(best[1]) if best else 0, "stage": "none",
            "understood_as": fixed, "suggestions": random.sample(SAMPLES, 3)}


def reply(idx, score, stage, understood, original):
    return {"matched": True, "answer": DATA[idx]["a"], "score": score, "stage": stage,
            "understood_as": understood if understood != original else ""}
