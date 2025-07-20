# main.py
import socketio
from fastapi import FastAPI
from gemini import chat_with_gemini
from db import SessionLocal
import logging
import json
from sqlalchemy import text

# Logger
# logging.basicConfig(filename="chat_logs.log", format="%(asctime)s - %(message)s", level=logging.INFO)

# FastAPI + SocketIO Setup
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI()
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Skill Fetch
def get_all_skills():
    db = SessionLocal()
    result = db.execute(text('SELECT name FROM "Goalskills"'))
    skills = [row[0] for row in result.fetchall()]
    db.close()
    return skills
    
# SQL Executor
def execute_sql(query: str):
    try:
        db = SessionLocal()
        result = db.execute(text(query))
        rows = result.fetchall()
        columns = result.keys()
        db.close()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return f"❌ DB Error: {e}"

# In-memory session memory
session_memory = {}

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    await sio.emit("chat_response", "✅ Connected to Gemini Goal Bot!", to=sid)

    # Init memory for session
    all_skills = get_all_skills()
    skill_list = ", ".join(f'"{skill}"' for skill in all_skills)

    memory = {
        "learning": None,
        "role": None,
        "selected_skill": None,
        "selected_subskill": None,
        "goal_set": False,
        "history": []
    }

    session_memory[sid] = memory

    system_prompt = f"""
You are a goal-setting assistant that guides students in defining their learning and career paths step-by-step.

Here is the list of skills from the database you must rely on:
[{skill_list}]

Maintain a short-term memory of the user's responses so far. These include:
- What the user is currently learning
- The role or goal they are aiming for
- Skills or subskills selected
- Whether their goal is confirmed

Always respond ONLY in this JSON format:

{{
  "is_sql_query": true | false,
  "sql_query": "SQL-like query string if needed, otherwise empty",
  "is_response": true | false,
  "is_goal_set": true | false,
  "response": {{
    "intent": "start" | "explore_goal" | "ask_learning" | "ask_role" | "fetch_skills" | "confirm_goal" | "show_subskills" | "show_syllabus",
    "learning": "",
    "role": "",
    "selected_skill": "",
    "selected_subskill": "",
    "message": "Direct message to display to the student"
  }}
}}
"""
    gemini_intro = chat_with_gemini(system_prompt)
    await sio.emit("chat_response", gemini_intro, to=sid)

@sio.event
async def chat_message(sid, user_input):
    print(f"User ({sid}): {user_input}")
    memory = session_memory.get(sid)

    if not memory:
        await sio.emit("chat_response", "❌ Memory not found for session", to=sid)
        return

    memory["history"].append({"user": user_input})

    context_input = {
        "history": memory["history"],
        "memory": {
            "learning": memory["learning"],
            "role": memory["role"],
            "selected_skill": memory["selected_skill"],
            "selected_subskill": memory["selected_subskill"],
            "goal_set": memory["goal_set"]
        },
        "current_input": user_input
    }

    gemini_raw = chat_with_gemini(json.dumps(context_input))
    logging.info(f"{sid} - BOT: {gemini_raw}")
    memory["history"].append({"bot": gemini_raw})

    try:
        cleaned = gemini_raw.strip("```json").strip("```").strip()
        parsed = json.loads(cleaned)

        if parsed.get("is_sql_query"):
            sql = parsed.get("sql_query")
            result = execute_sql(sql)
            await sio.emit("sql_result", result, to=sid)

        if parsed.get("is_response"):
            msg = parsed["response"].get("message")
            await sio.emit("chat_response", msg, to=sid)

            # Update memory
            for key in ["learning", "role", "selected_skill", "selected_subskill"]:
                if parsed["response"].get(key):
                    memory[key] = parsed["response"][key]

        if parsed.get("is_goal_set"):
            memory["goal_set"] = True
            await sio.emit("chat_response", "✅ Goal is set.", to=sid)

    except Exception as e:
        await sio.emit("chat_response", f"❌ Error parsing Gemini: {e}", to=sid)

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    session_memory.pop(sid, None)
