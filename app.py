from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from groq import Groq
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
import uuid
import base64
from duckduckgo_search import DDGS
import tempfile
import os
from moviepy import VideoFileClip
from pydub import AudioSegment
import io
import zipfile
from pypdf import PdfReader
import PIL.Image
from urllib.parse import quote
import requests
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "studybot_secret_key_2024")
bcrypt = Bcrypt(app)

# ── MongoDB setup
MONGO_URI = os.environ.get("MONGO_URI")
mongo = MongoClient(MONGO_URI)
db = mongo["studybot"]
users_col = db["users"]
chats_col = db["chats"]

# ── API Keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
HF_API_KEY = os.environ.get("HF_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """
You are StudyBot, a friendly and intelligent study assistant designed for students.
Your job is to:
1. Explain any topic in simple, easy-to-understand language
2. Give real-life examples to make concepts clear
3. Quiz the student when they ask to be tested
4. Encourage and motivate students when they struggle
Keep responses concise and clear.
"""

# ── Login required decorator
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ── Reads any file and returns its text content
def extract_file_content(file_data, filename):
    content = ""
    if filename.endswith(".pdf"):
        pdf = PdfReader(io.BytesIO(file_data))
        for page in pdf.pages:
            content += page.extract_text()
    elif filename.endswith(".txt"):
        content = file_data.decode("utf-8")
    elif filename.endswith(".csv"):
        content = file_data.decode("utf-8")
    elif filename.endswith(".zip"):
        zip_file = zipfile.ZipFile(io.BytesIO(file_data))
        for name in zip_file.namelist():
            with zip_file.open(name) as f:
                file_bytes = f.read()
                if name.endswith(".pdf"):
                    pdf = PdfReader(io.BytesIO(file_bytes))
                    for page in pdf.pages:
                        content += f"\n[From {name}]\n"
                        content += page.extract_text()
                elif name.endswith(".txt") or name.endswith(".csv"):
                    content += f"\n[From {name}]\n"
                    content += file_bytes.decode("utf-8", errors="ignore")
    else:
        content = "Unsupported file type."
    return content

# ── Checks if user is requesting an image
def is_image_request(message):
    image_keywords = [
        "draw", "generate image", "create image", "generate an image",
        "create an image", "make an image", "show me a picture",
        "visualize", "illustrate", "diagram", "flowchart", "sketch",
        "paint", "render", "picture of", "image of", "generate a picture",
        "create a diagram", "make a diagram", "flow chart",
        "generate the image", "create the image", "make the image",
        "show image", "give me image", "give me a picture",
        "generate me", "draw me", "image of the", "photo of",
        "photograph of", "can you generate", "able to generate",
        "generate picture", "create picture", "show me an image",
        "show me a diagram", "show me a photo"
    ]
    message_lower = message.lower()
    for keyword in image_keywords:
        if keyword in message_lower:
            return True
    return False

# ── Generates image using HuggingFace FLUX and returns base64
def generate_image_base64(prompt):
    response = requests.post(
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        headers={"Authorization": f"Bearer {HF_API_KEY}", "Content-Type": "application/json"},
        json={"inputs": prompt},
        timeout=60
    )
    response.raise_for_status()
    image_b64 = base64.b64encode(response.content).decode("utf-8")
    return f"data:image/jpeg;base64,{image_b64}"

# ── Get chat messages from MongoDB
def get_chat_messages(chat_id):
    chat = chats_col.find_one({"chat_id": chat_id})
    return chat["messages"] if chat else []

# ── Save chat messages to MongoDB
def save_chat_messages(chat_id, messages):
    chats_col.update_one({"chat_id": chat_id}, {"$set": {"messages": messages}}, upsert=True)

# ════════════════════════════════════════
#  AUTH ROUTES
# ════════════════════════════════════════

@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return render_template("index.html", username=session.get("username"))

@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("auth.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not username or not email or not password:
        return jsonify({"error": "All fields are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if users_col.find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 400
    if users_col.find_one({"username": username}):
        return jsonify({"error": "Username already taken"}), 400

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    user_id = str(uuid.uuid4())
    users_col.insert_one({
        "user_id": user_id,
        "username": username,
        "email": email,
        "password": hashed_pw,
        "created_at": datetime.utcnow()
    })
    session["user_id"] = user_id
    session["username"] = username
    return jsonify({"success": True, "username": username})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    identifier = data.get("identifier", "").strip().lower()
    password = data.get("password", "")

    user = users_col.find_one({"$or": [{"email": identifier}, {"username": identifier}]})
    if not user or not bcrypt.check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid email/username or password"}), 401

    session["user_id"] = user["user_id"]
    session["username"] = user["username"]
    return jsonify({"success": True, "username": user["username"]})

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "username": session.get("username")})

# ════════════════════════════════════════
#  CHAT ROUTES
# ════════════════════════════════════════

@app.route("/new-chat", methods=["POST"])
@login_required
def new_chat():
    chat_id = str(uuid.uuid4())[:8]
    chats_col.insert_one({
        "chat_id": chat_id,
        "user_id": session["user_id"],
        "title": "New Chat",
        "messages": [],
        "created_at": datetime.utcnow()
    })
    return jsonify({"chat_id": chat_id})

@app.route("/chat", methods=["POST"])
@login_required
def chat_route():
    data = request.json
    user_message = data["message"]
    chat_id = data["chat_id"]

    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    if not chat:
        return jsonify({"error": "Chat not found"}), 404

    messages = chat["messages"]

    if len(messages) == 0:
        chats_col.update_one({"chat_id": chat_id}, {"$set": {"title": user_message[:30]}})

    if is_image_request(user_message):
        check_response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helper that checks if an image generation request has enough detail. Reply with only YES or NO."},
                {"role": "user", "content": f"Does this have enough detail to generate an image: '{user_message}'"}
            ]
        )
        has_detail = "YES" in check_response.choices[0].message.content.upper()

        if not has_detail:
            messages.append({"role": "user", "content": user_message})
            messages.append({"role": "assistant", "content": "Asked user for image details"})
            save_chat_messages(chat_id, messages)
            return jsonify({"reply": "Sure! What would you like me to generate an image of? Please describe it in detail! 😊", "ask_image_prompt": True})

        image_data = generate_image_base64(user_message)
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": f"[Generated Image] {user_message}"})
        save_chat_messages(chat_id, messages)
        return jsonify({"reply": "Here is the image you requested!", "image_data": image_data, "prompt": user_message})

    messages.append({"role": "user", "content": user_message})
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages
    )
    ai_reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": ai_reply})
    save_chat_messages(chat_id, messages)
    return jsonify({"reply": ai_reply})

@app.route("/get-chats", methods=["GET"])
@login_required
def get_chats():
    user_chats = chats_col.find({"user_id": session["user_id"]}, sort=[("created_at", -1)])
    chat_list = [{"id": c["chat_id"], "title": c["title"]} for c in user_chats]
    return jsonify({"chats": chat_list})

@app.route("/load-chat", methods=["POST"])
@login_required
def load_chat():
    chat_id = request.json["chat_id"]
    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    if not chat:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"messages": chat["messages"], "title": chat["title"]})

@app.route("/rename-chat", methods=["POST"])
@login_required
def rename_chat():
    chat_id = request.json["chat_id"]
    new_title = request.json["new_title"]
    chats_col.update_one({"chat_id": chat_id, "user_id": session["user_id"]}, {"$set": {"title": new_title}})
    return jsonify({"status": "renamed"})

@app.route("/delete-chat", methods=["POST"])
@login_required
def delete_chat():
    chat_id = request.json["chat_id"]
    chats_col.delete_one({"chat_id": chat_id, "user_id": session["user_id"]})
    return jsonify({"status": "deleted"})

@app.route("/upload-file", methods=["POST"])
@login_required
def upload_file():
    file = request.files["file"]
    filename = file.filename
    chat_id = request.form.get("chat_id")
    user_message = request.form.get("message", "Please analyze this file.")
    file_data = file.read()
    content = extract_file_content(file_data, filename)

    if not content or content == "Unsupported file type.":
        return jsonify({"reply": "Sorry, I couldn't read this file type!"})

    if len(content) > 3000:
        content = content[:3000] + "...(content trimmed)"

    prompt = f"{user_message}\n\nFile name: {filename}\nFile content:\n{content}"
    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    messages = chat["messages"]
    messages.append({"role": "user", "content": f"[File: {filename}] {user_message}"})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages + [{"role": "user", "content": prompt}]
    )
    ai_reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": ai_reply})
    save_chat_messages(chat_id, messages)

    if len(messages) == 2:
        chats_col.update_one({"chat_id": chat_id}, {"$set": {"title": f"📁 {filename}"[:30]}})

    return jsonify({"reply": ai_reply})

@app.route("/analyze-image", methods=["POST"])
@login_required
def analyze_image():
    data = request.json
    image_data = data["image"]
    user_message = data.get("message", "What do you see in this image?")
    chat_id = data["chat_id"]

    if "," in image_data:
        image_data = image_data.split(",")[1]

    image_type = "png" if "png" in data["image"] else "jpeg"

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{image_type};base64,{image_data}"}},
                {"type": "text", "text": user_message}
            ]
        }]
    )
    ai_reply = response.choices[0].message.content
    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    messages = chat["messages"]
    messages.append({"role": "user", "content": f"[Image] {user_message}"})
    messages.append({"role": "assistant", "content": ai_reply})
    save_chat_messages(chat_id, messages)
    return jsonify({"reply": ai_reply})

@app.route("/web-search", methods=["POST"])
@login_required
def web_search():
    data = request.json
    query = data["query"]
    chat_id = data["chat_id"]

    results = []
    with DDGS() as ddgs:
        for result in ddgs.text(query, max_results=5):
            results.append({"title": result["title"], "body": result["body"], "link": result["href"]})

    search_text = f"Web search results for: {query}\n\n"
    for i, r in enumerate(results, 1):
        search_text += f"{i}. {r['title']}\n   {r['body']}\n   Source: {r['link']}\n\n"

    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    messages = chat["messages"]
    messages.append({"role": "user", "content": f"[Web Search] {query}"})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages + [
            {"role": "user", "content": f"Based on these web search results, give a clear and helpful summary:\n\n{search_text}"}
        ]
    )
    ai_reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": ai_reply})
    save_chat_messages(chat_id, messages)
    chats_col.update_one({"chat_id": chat_id}, {"$set": {"title": f"🌐 {query}"[:30]}})
    return jsonify({"reply": ai_reply, "sources": results})

@app.route("/analyze-video", methods=["POST"])
@login_required
def analyze_video():
    tmp_video_path = None
    tmp_audio_path = None
    try:
        video_file = request.files["video"]
        chat_id = request.form.get("chat_id")
        user_message = request.form.get("message", "Analyze this video and explain what you see.")

        original_ext = os.path.splitext(video_file.filename)[1] or ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_ext) as tmp_video:
            video_file.save(tmp_video.name)
            tmp_video_path = tmp_video.name

        tmp_audio_path = tmp_video_path.rsplit(".", 1)[0] + ".mp3"

        # ── Extract and transcribe audio
        speech_text = "No speech detected"
        try:
            vc = VideoFileClip(tmp_video_path)
            if vc.audio is not None:
                vc.audio.write_audiofile(tmp_audio_path, logger=None)
                vc.close()
                with open(tmp_audio_path, "rb") as af:
                    result = client.audio.transcriptions.create(
                        model="whisper-large-v3", file=af, response_format="text"
                    )
                    if result and result.strip():
                        speech_text = result.strip()
            else:
                vc.close()
        except Exception:
            pass

        # ── Extract middle frame for visual analysis
        visual_analysis = "No visual analysis available"
        try:
            vc2 = VideoFileClip(tmp_video_path)
            frame = vc2.get_frame(vc2.duration / 2)
            vc2.close()
            img = PIL.Image.fromarray(frame)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            frame_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            vis_resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}},
                    {"type": "text", "text": "Describe in detail what you see in this video frame."}
                ]}]
            )
            visual_analysis = vis_resp.choices[0].message.content
        except Exception:
            pass

        combined_prompt = f"""The user uploaded a video. Analyze it fully using both sources below:

AUDIO TRANSCRIPT:
{speech_text}

VISUAL FRAME ANALYSIS:
{visual_analysis}

USER'S QUESTION: {user_message}

Give a detailed, helpful response based on the audio transcript and visual content."""

        chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
        messages = chat["messages"]
        messages.append({"role": "user", "content": f"[Video] {user_message}"})
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages + [{"role": "user", "content": combined_prompt}]
        )
        ai_reply = response.choices[0].message.content
        messages.append({"role": "assistant", "content": ai_reply})
        save_chat_messages(chat_id, messages)
        chats_col.update_one({"chat_id": chat_id}, {"$set": {"title": "🎬 Video Analysis"}})
        return jsonify({"reply": ai_reply, "transcript": speech_text})

    except Exception as e:
        return jsonify({"reply": f"Error processing video: {str(e)}"})
    finally:
        for p in [tmp_video_path, tmp_audio_path]:
            if p and os.path.exists(p):
                try: os.unlink(p)
                except: pass

@app.route("/generate-image", methods=["POST"])
@login_required
def generate_image():
    data = request.json
    prompt = data["prompt"]
    chat_id = data["chat_id"]

    try:
        image_data = generate_image_base64(prompt)
    except Exception as e:
        return jsonify({"error": f"Image generation failed: {str(e)}"}), 500

    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    messages = chat["messages"]
    messages.append({"role": "user", "content": f"[Image Request] {prompt}"})
    messages.append({"role": "assistant", "content": f"[Generated Image] {prompt}"})
    save_chat_messages(chat_id, messages)
    chats_col.update_one({"chat_id": chat_id}, {"$set": {"title": f"🎨 {prompt}"[:30]}})
    return jsonify({"image_data": image_data, "prompt": prompt})

@app.route("/quiz", methods=["POST"])
@login_required
def quiz():
    data = request.json
    topic = data["topic"]
    chat_id = data["chat_id"]

    chat = chats_col.find_one({"chat_id": chat_id, "user_id": session["user_id"]})
    messages = chat["messages"]

    quiz_prompt = f"""You are now in QUIZ MODE for the topic: {topic}
Ask ONE question, wait for answer, tell if RIGHT or WRONG, explain, then ask another.
Keep track of score. Be encouraging! Start with your first question now!"""

    messages.append({"role": "user", "content": f"[Quiz Mode] Topic: {topic}"})
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages + [{"role": "user", "content": quiz_prompt}]
    )
    ai_reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": ai_reply})
    save_chat_messages(chat_id, messages)
    chats_col.update_one({"chat_id": chat_id}, {"$set": {"title": f"📝 Quiz: {topic}"[:30]}})
    return jsonify({"reply": ai_reply})

@app.route("/sw.js")
def sw():
    return app.send_static_file("sw.js"), 200, {"Content-Type": "application/javascript"}

@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json"), 200, {"Content-Type": "application/json"}

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
