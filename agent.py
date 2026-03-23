from groq import Groq
from dotenv import load_dotenv
import os
load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# This is the agent's personality and purpose
SYSTEM_PROMPT = """
You are StudyBot, a friendly and intelligent study assistant designed for students.
Your job is to:
1. Explain any topic in simple, easy-to-understand language
2. Give real-life examples to make concepts clear
3. Quiz the student when they ask to be tested
4. Encourage and motivate students when they struggle
5. Break down complex topics into small, digestible steps

Always be friendly, patient, and supportive. 
If a student is confused, explain it differently.
Keep responses concise and clear.
"""

# Conversation history
messages = []

def chat(user_message):
    messages.append({"role": "user", "content": user_message})
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT}
        ] + messages
    )
    
    ai_reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": ai_reply})
    
    return ai_reply

# Run the Study Assistant
print("=" * 50)
print("       Welcome to StudyBot! 🎓")
print("  Your personal AI Study Assistant")
print("=" * 50)
print("Type 'quit' to exit")
print()

while True:
    user_input = input("You: ")
    if user_input.lower() == "quit":
        print("Good luck with your studies! Goodbye! 👋")
        break
    response = chat(user_input)
    print(f"\nStudyBot: {response}\n")