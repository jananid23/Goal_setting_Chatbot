import google.generativeai as genai
from config import Config

genai.configure(api_key=Config.GEMINI_API_KEY)

# Create a chat model
model = genai.GenerativeModel("gemini-2.0-flash-lite")
chat = model.start_chat(history=[])

def chat_with_gemini(user_input: str) -> str:
    response = chat.send_message(user_input)
    return response.text
