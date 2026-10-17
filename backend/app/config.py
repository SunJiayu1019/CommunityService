import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("LLM_API_KEY", "").strip()
BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.getenv("LLM_MODEL", "qwen-plus")
DB_PATH = os.getenv("DB_PATH", "data/community.db")
VECTOR_PATH = os.getenv("VECTOR_PATH", "data/chroma")
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))
SYSTEM_PROMPT = (
    "你是社区生活服务智能管家。只根据工具返回的真实数据回答，不编造公告、费用、工单状态或维修进度。"
    "使用简体中文，先给结论，再给必要的步骤；缺少报修信息时要继续追问。"
)
