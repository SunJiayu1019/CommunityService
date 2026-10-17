import hashlib
import html
import ipaddress
import json
import logging
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import BASE_DIR, VECTOR_PATH

VECTOR_DIR = Path(VECTOR_PATH)
if not VECTOR_DIR.is_absolute():
    VECTOR_DIR = BASE_DIR / VECTOR_DIR

def ensure_vector_store():
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    records_path = VECTOR_DIR / "langchain-records.json"
    if not records_path.exists():
        return
    try:
        from langchain_chroma import Chroma
    except ImportError:
        return
    try:
        records = json.loads(records_path.read_text(encoding="utf-8"))
        if not records:
            return
        store = Chroma(collection_name="community_knowledge", persist_directory=str(VECTOR_DIR), embedding_function=LocalEmbeddings())
        if store._collection.count() == 0:
            store.add_texts([item["text"] for item in records],
                            metadatas=[item["metadata"] for item in records],
                            ids=[item["id"] for item in records])
    except Exception:
        logging.getLogger(__name__).exception("Could not migrate the local LangChain index to Chroma")

class LocalEmbeddings:
    """Deterministic local embeddings keep the demo usable without an API key."""
    def _embed(self, text: str):
        values = [0.0] * 128
        for token in re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % len(values)
            values[index] += 1.0
        norm = sum(x * x for x in values) ** 0.5 or 1.0
        return [x / norm for x in values]

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)

class FallbackVectorStore:
    """LangChain's durable local vector store fallback for environments without Chroma."""
    def __init__(self):
        from langchain_core.vectorstores import InMemoryVectorStore
        self.path = VECTOR_DIR / "langchain-index.json"
        self.records_path = VECTOR_DIR / "langchain-records.json"
        embeddings = LocalEmbeddings()
        self.store = InMemoryVectorStore.load(str(self.path), embedding=embeddings) if self.path.exists() else InMemoryVectorStore(embedding=embeddings)
        self.records = json.loads(self.records_path.read_text(encoding="utf-8")) if self.records_path.exists() else []

    def add_texts(self, texts, metadatas, ids):
        self.store.add_texts(texts, metadatas=metadatas, ids=ids)
        self.store.dump(str(self.path))
        self.records = [item for item in self.records if item["id"] not in ids]
        self.records.extend({"id": i, "text": t, "metadata": m} for i, t, m in zip(ids, texts, metadatas))
        self.records_path.write_text(json.dumps(self.records, ensure_ascii=False), encoding="utf-8")

    def similarity_search(self, query, k=3):
        return self.store.similarity_search(query, k=k)

    def delete(self, ids):
        self.store.delete(ids=ids)
        self.store.dump(str(self.path))
        self.records = [item for item in self.records if item["id"] not in ids]
        self.records_path.write_text(json.dumps(self.records, ensure_ascii=False), encoding="utf-8")

    def ids_for_document(self, document_id: str):
        return [key for key, item in self.store.store.items() if item.get("metadata", {}).get("document_id") == document_id]

def get_vector_store():
    ensure_vector_store()
    try:
        from langchain_chroma import Chroma
    except ImportError:
        logging.getLogger(__name__).warning("Chroma is unavailable; using durable fallback vector index at %s", VECTOR_DIR)
        return FallbackVectorStore()
    return Chroma(
        collection_name="community_knowledge",
        persist_directory=str(VECTOR_DIR),
        embedding_function=LocalEmbeddings(),
    )

def split_text(text: str, size: int = 800, overlap: int = 120):
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks

def extract_web(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("网页地址必须是 http 或 https URL")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except OSError as exc:
        raise ValueError("无法解析网页域名") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("为避免访问内网地址，仅允许公网网页")

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("网页重定向不受支持，请直接填写最终网页地址")

    request = Request(url, headers={"User-Agent": "CommunityServiceKnowledgeBot/1.0"})
    with build_opener(NoRedirect).open(request, timeout=12) as response:
        raw = response.read(2_000_000)
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", raw.decode("utf-8", errors="ignore"))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()

def extract_pdf(content: bytes):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf 依赖，请重新安装 backend/requirements.txt") from exc
    import io
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def index_document(document_id: str, title: str, source_type: str, source: str, content: str):
    chunks = split_text(content)
    if not chunks:
        raise ValueError("资料没有可提取的文字内容")
    store = get_vector_store()
    ids = [f"{document_id}:{i}" for i in range(len(chunks))]
    metadatas = [{"document_id": document_id, "title": title, "source_type": source_type} for _ in chunks]
    store.add_texts(chunks, metadatas=metadatas, ids=ids)
    return len(chunks)

def search_knowledge(query: str, limit: int = 3):
    try:
        store = get_vector_store()
        docs = store.similarity_search(query, k=limit)
        if docs:
            return [doc.page_content for doc in docs]
    except Exception:
        logging.getLogger(__name__).exception("Knowledge vector search failed")
    records_path = VECTOR_DIR / "langchain-records.json"
    if not records_path.exists():
        return []
    query_terms = set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", query.lower()))
    records = json.loads(records_path.read_text(encoding="utf-8"))
    ranked = sorted(records, key=lambda item: len(query_terms & set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", item["text"].lower()))), reverse=True)
    matches = [item["text"] for item in ranked if query_terms & set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", item["text"].lower()))]
    return matches[:limit]

def delete_document_vectors(document_id: str):
    store = get_vector_store()
    if isinstance(store, FallbackVectorStore):
        ids = store.ids_for_document(document_id)
        store.delete(ids=ids)
        return len(ids)
    result = store._collection.get(where={"document_id": document_id}, include=[])
    ids = result.get("ids", [])
    if ids: store.delete(ids=ids)
    return len(ids)

def new_document_id():
    return "K" + uuid.uuid4().hex[:12].upper()
