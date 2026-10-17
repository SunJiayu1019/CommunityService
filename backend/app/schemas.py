from typing import Literal, Optional
from pydantic import BaseModel, Field

class SessionCreate(BaseModel):
    title: str = Field(default="新对话", max_length=80)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None

class RepairRequest(BaseModel):
    resident: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$", description="中国大陆手机号")
    location: str = Field(..., min_length=2, max_length=120)
    category: str = Field(..., min_length=1, max_length=30)
    description: str = Field(..., min_length=2, max_length=500)
    urgency: Literal["普通", "紧急"] = "普通"
    appointment: str = Field(default="尽快安排", max_length=50)

class RepairUpdate(BaseModel):
    location: Optional[str] = Field(default=None, min_length=2, max_length=120)
    category: Optional[str] = Field(default=None, min_length=1, max_length=30)
    description: Optional[str] = Field(default=None, min_length=2, max_length=500)
    urgency: Optional[Literal["普通", "紧急"]] = None
    appointment: Optional[str] = Field(default=None, max_length=50)
    status: Optional[Literal["待受理", "处理中", "已完成", "已取消"]] = None

class KnowledgeTextRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=2, max_length=200000)

class KnowledgeWebRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=8, max_length=2000)
