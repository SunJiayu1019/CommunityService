# 社区生活服务智能管家

## 本地启动

### 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000/docs` 查看 Swagger。`LLM_API_KEY` 留空也能使用离线工具模式；填写 OpenAI 兼容 API Key 可为后续模型增强预留配置。

### 前端

```powershell
cd frontend
npm run dev
```

打开 `http://localhost:5173`。

## Docker 启动

先复制 `backend/.env.example` 为 `backend/.env`，再执行：

```powershell
docker compose up -d --build
```

访问 `http://localhost:8080`。停止服务：`docker compose down`；SQLite 数据保存在 `backend/data`，容器重建后仍然保留。

## 验证

```powershell
cd backend
python test_smoke.py
```
