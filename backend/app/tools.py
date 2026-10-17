import re
import uuid
from sqlalchemy.orm import Session
from .models import Facility, Notice, RepairDraft, RepairOrder
from .schemas import RepairRequest

def search_notice(db: Session, keyword: str = ""):
    q = db.query(Notice)
    if keyword:
        q = q.filter((Notice.title.contains(keyword)) | (Notice.content.contains(keyword)) | (Notice.category.contains(keyword)))
    rows = q.order_by(Notice.created_at.desc()).limit(5).all()
    return [{"title": x.title, "category": x.category, "content": x.content} for x in rows]

def query_facility(db: Session, name: str):
    row = db.query(Facility).filter(Facility.name.contains(name)).first()
    if not row:
        return {"found": False, "message": "未找到该设施，请换一个名称试试。"}
    return {"found": True, "name": row.name, "location": row.location, "hours": row.hours, "description": row.description}

def create_repair_order(db: Session, data: dict):
    order_id = "R" + uuid.uuid4().hex[:8].upper()
    row = RepairOrder(id=order_id, **data)
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return repair_to_dict(row)
    except Exception:
        db.rollback()
        raise

def get_repair_status(db: Session, order_id: str):
    row = db.query(RepairOrder).filter(RepairOrder.id == order_id.upper()).first()
    return repair_to_dict(row) if row else {"found": False, "message": "未找到该工单，请检查编号。"}

def list_repairs(db: Session, phone: str):
    rows = db.query(RepairOrder).filter(RepairOrder.phone == phone).order_by(RepairOrder.created_at.desc()).limit(10).all()
    return [repair_to_dict(x) for x in rows]

def repair_to_dict(row):
    if not row: return None
    return {"id": row.id, "resident": row.resident, "phone": row.phone, "location": row.location,
            "category": row.category, "description": row.description, "urgency": row.urgency,
            "status": row.status, "appointment": row.appointment,
            "created_at": row.created_at.isoformat() if row.created_at else None}

def infer_repair_data(text: str):
    category = "其他"
    for key, value in [("漏水", "水管"), ("停水", "水管"), ("漏电", "电路"), ("跳闸", "电路"), ("门禁", "门禁"), ("电梯", "电梯"), ("空调", "空调")]:
        if key in text: category = value; break
    urgency = "紧急" if any(k in text for k in ["紧急", "马上", "立即", "危险"]) else "普通"
    return category, urgency

REPAIR_KEYWORDS = ["报修", "维修", "修理", "漏水", "漏电", "跳闸", "故障", "坏了", "不亮", "不通", "电梯", "门禁", "水管", "空调"]

def has_repair_intent(text: str) -> bool:
    return any(keyword in text for keyword in REPAIR_KEYWORDS)

def get_repair_draft(db: Session, session_id: str):
    return db.query(RepairDraft).filter(RepairDraft.session_id == session_id).first()

def extract_repair_fields(text: str, is_initial: bool = False) -> dict:
    """从常见中文表达中提取字段；模型不可用时仍可完成基础报修。"""
    fields = {}
    phone = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", text)
    if phone:
        fields["phone"] = phone.group(1)

    resident = re.search(r"(?:我叫|姓名(?:是|为|[:：])?|联系人(?:是|为|[:：])?)[：:\s]*([\u4e00-\u9fa5A-Za-z·]{2,20})", text)
    if resident:
        name = resident.group(1)
        for stop in ["电话", "手机", "住在", "地址", "位置"]:
            name = name.split(stop, 1)[0]
        if 1 < len(name) <= 20:
            fields["resident"] = name

    location = re.search(r"(?:住在|地址(?:是|为|[:：])?|位置(?:是|为|[:：])?|地点(?:是|为|[:：])?)[：:\s]*([^，。；;\n]{2,80})", text)
    if location:
        value = re.split(r"(?:电话|手机|联系人|姓名|故障|问题|描述)", location.group(1))[0].strip(" ，。")
        if len(value) >= 2:
            fields["location"] = value
    elif re.fullmatch(r"\s*(?:\d+号(?:楼|栋|院|单元)|[一二三四五六七八九十]+号(?:楼|栋))(?:\d+单元)?(?:\d{2,4}(?:室)?)?\s*", text):
        fields["location"] = text.strip()

    category, urgency = infer_repair_data(text)
    if category != "其他":
        fields["category"] = category
    if urgency == "紧急" or any(k in text for k in ["普通", "不着急"]):
        fields["urgency"] = urgency

    appointment = re.search(r"(?:预约|上门时间|时间)[：:\s]*(今天|明天|后天|尽快|[^，。；;\n]{2,30})", text)
    if appointment:
        fields["appointment"] = appointment.group(1).strip()

    if is_initial and has_repair_intent(text):
        description = re.sub(r"(?:我想|我要|需要|帮我|请|怎么|如何|可以)?(?:报修|维修|修理)", "", text).strip(" ，。？?")
        if len(description) >= 2:
            fields["description"] = description[:500]
    elif any(label in text for label in ["故障", "问题", "描述"]):
        description = re.sub(r"^.*?(?:故障|问题|描述)(?:是|为|[:：])?", "", text).strip(" ，。")
        if len(description) >= 2:
            fields["description"] = description[:500]
    return fields

def update_repair_draft(db: Session, session_id: str, text: str):
    draft = get_repair_draft(db, session_id)
    is_initial = draft is None
    if draft is None:
        draft = RepairDraft(session_id=session_id)
        db.add(draft)
    fields = extract_repair_fields(text, is_initial=is_initial)
    stripped = text.strip(" ，。；;：:")
    # 支持按照追问逐项回答，不强迫用户重复“姓名/描述”等标签。
    if not draft.resident and "resident" not in fields and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z·]{2,20}", stripped) and not has_repair_intent(stripped):
        fields["resident"] = stripped
    if not draft.description and "description" not in fields and has_repair_intent(stripped):
        fields["description"] = stripped[:500]
    for key, value in fields.items():
        setattr(draft, key, value)
    db.flush()
    return draft

def missing_repair_fields(draft: RepairDraft) -> list[str]:
    labels = {"resident": "姓名", "phone": "联系电话", "location": "详细位置", "description": "故障描述"}
    return [label for field, label in labels.items() if not getattr(draft, field)]

def complete_repair_draft(db: Session, draft: RepairDraft):
    """先经 RepairRequest 校验，再写 repair_orders，确保无半成品工单。"""
    request = RepairRequest(
        resident=draft.resident,
        phone=draft.phone,
        location=draft.location,
        category=draft.category or "其他",
        description=draft.description,
        urgency=draft.urgency or "普通",
        appointment=draft.appointment or "尽快安排",
    )
    try:
        row = RepairOrder(id="R" + uuid.uuid4().hex[:8].upper(), **request.model_dump())
        db.add(row)
        db.delete(draft)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise
    return repair_to_dict(row)
