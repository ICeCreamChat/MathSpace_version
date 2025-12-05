# config.py
"""
MathSpace 系统配置
"""

# ================= ⚡ API 配置 =================
API_KEY = "sk-80fd74758c144a61b2dae7a23195614c" 
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

# ================= 📂 路径配置 =================
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TEMP_DIR = os.path.join(BASE_DIR, "temp_gen") 
SCENE_FILE = os.path.join(TEMP_DIR, "current_scene.py") 
HISTORY_FILE = os.path.join(TEMP_DIR, "context_history.txt")
CONVERSATION_FILE = os.path.join(TEMP_DIR, "conversation.json")

# ================= ⚙️ 系统配置 =================
MAX_RETRIES = 2
MAX_HISTORY_ENTRIES = 15
REQUEST_TIMEOUT = 120.0
MANIM_TIMEOUT = 300

# ================= 🎯 默认值 =================
DEFAULT_SCENE_NAME = "MathScene"
DEFAULT_QUALITY = "-ql"  # 低质量，快速渲染