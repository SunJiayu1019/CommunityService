<script setup>
import { computed, ref, onMounted } from 'vue'

const role = ref('resident')
const active = ref('assistant')
const phone = ref(localStorage.getItem('residentPhone') || '13800000000')
const messages = ref([{ role: 'assistant', content: '你好，我是社区生活服务智能管家。你可以查询物业信息、设施位置，或直接描述需要报修的问题。' }])
const input = ref(''); const sessionId = ref(null); const loading = ref(false); const tools = ref([])
const repairs = ref([]); const repairLoading = ref(false); const editing = ref(null); const notice = ref('')
const knowledge = ref({ title: '', source: 'text', content: '' })
const knowledgeFile = ref(null); const knowledgeDocs = ref([]); const knowledgeLoading = ref(false)
const isAdmin = computed(() => role.value === 'admin')
const nav = [
  { id: 'assistant', label: '智能助手', icon: '✦', desc: '查询与报修' },
  { id: 'repairs', label: '报修工单', icon: '▤', desc: '查看处理进度' },
  { id: 'knowledge', label: '知识库扩展', icon: '⌁', desc: '管理员功能', admin: true },
]
function headers() { return { 'Content-Type': 'application/json', 'X-User-Role': role.value, 'X-User-Phone': phone.value } }
async function send() {
  const text = input.value.trim(); if (!text || loading.value) return
  messages.value.push({ role: 'user', content: text }); input.value = ''; loading.value = true
  try {
    const r = await fetch('/api/agent/chat', { method: 'POST', headers: headers(), body: JSON.stringify({ message: text, session_id: sessionId.value }) })
    const payload = await r.json(); if (!r.ok) throw new Error(payload.message)
    const d = payload.data; sessionId.value = d.session_id; messages.value.push({ role: 'assistant', content: d.reply }); tools.value = d.tools_used || []
    if (d.repair?.status === 'created') { phone.value = d.repair.order.phone; localStorage.setItem('residentPhone', phone.value); notice.value = `工单 ${d.repair.order.id} 已创建`; await loadRepairs() }
  } catch { messages.value.push({ role: 'assistant', content: '服务暂时不可用，请稍后重试。' }) } finally { loading.value = false }
}
async function quick(text) { input.value = text; await send() }
async function loadRepairs() {
  repairLoading.value = true
  const query = isAdmin.value ? '' : `?phone=${encodeURIComponent(phone.value)}`
  try { const r = await fetch(`/api/repairs${query}`, { headers: headers() }); repairs.value = (await r.json()).data || [] } finally { repairLoading.value = false }
}
function switchRole(next) { role.value = next; active.value = 'assistant'; notice.value = next === 'admin' ? '已切换为管理员视角' : '已切换为住户视角'; loadRepairs(); if (next === 'admin') loadKnowledge() }
function canEdit(item) { return isAdmin.value || item.phone === phone.value }
async function updateRepair(item) {
  const r = await fetch(`/api/repairs/${item.id}`, { method: 'PUT', headers: headers(), body: JSON.stringify({ location: item.location, category: item.category, description: item.description, urgency: item.urgency, status: isAdmin.value ? item.status : undefined }) })
  if (r.ok) { editing.value = null; notice.value = '工单已更新'; await loadRepairs() } else notice.value = (await r.json()).detail || '更新失败'
}
async function removeRepair(item) {
  if (!isAdmin.value || !confirm(`确认删除工单 ${item.id}？`)) return
  const r = await fetch(`/api/repairs/${item.id}`, { method: 'DELETE', headers: headers() }); if (r.ok) { notice.value = '工单已删除'; await loadRepairs() }
}
async function loadKnowledge() {
  if (!isAdmin.value) return
  const r = await fetch('/api/admin/knowledge/documents', { headers: headers() })
  const payload = await r.json()
  if (r.ok) knowledgeDocs.value = payload.data || []
}
function switchKnowledgeSource() { knowledgeFile.value = null; knowledge.value.content = '' }
async function submitKnowledge() {
  if (knowledgeLoading.value) return
  knowledgeLoading.value = true
  try {
    const title = knowledge.value.title.trim()
    let response
    if (knowledge.value.source === 'text') {
      response = await fetch('/api/admin/knowledge/text', { method: 'POST', headers: headers(), body: JSON.stringify({ title, content: knowledge.value.content }) })
    } else if (knowledge.value.source === 'pdf') {
      const file = knowledgeFile.value?.files?.[0]
      if (!file) throw new Error('请先选择 PDF 文件')
      const data = new FormData(); data.append('title', title); data.append('file', file)
      response = await fetch('/api/admin/knowledge/pdf', { method: 'POST', headers: { 'X-User-Role': role.value, 'X-User-Phone': phone.value }, body: data })
    } else {
      response = await fetch('/api/admin/knowledge/web', { method: 'POST', headers: headers(), body: JSON.stringify({ title, url: knowledge.value.content }) })
    }
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail || payload.message || '资料入库失败')
    notice.value = `${payload.data.title} 已完成向量入库，共 ${payload.data.chunk_count} 个文本片段`
    knowledge.value = { title: '', source: knowledge.value.source, content: '' }
    knowledgeFile.value = null
    await loadKnowledge()
  } catch (error) { notice.value = error.message || '资料入库失败' }
  finally { knowledgeLoading.value = false }
}
async function removeKnowledge(doc) {
  if (!confirm(`确认删除知识资料“${doc.title}”及其向量索引？`)) return
  const r = await fetch(`/api/admin/knowledge/documents/${doc.id}`, { method: 'DELETE', headers: headers() })
  const payload = await r.json()
  if (!r.ok) { notice.value = payload.detail || '删除失败'; return }
  notice.value = `已删除资料“${doc.title}”`
  await loadKnowledge()
}
onMounted(loadRepairs)
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">+</span><div><strong>邻里管家</strong><small>COMMUNITY SERVICE</small></div></div>
      <div class="role-switch"><span>当前身份</span><button :class="{selected: role === 'resident'}" @click="switchRole('resident')">住户</button><button :class="{selected: role === 'admin'}" @click="switchRole('admin')">管理员</button></div>
      <nav><button v-for="item in nav" v-show="!item.admin || isAdmin" :key="item.id" :class="['nav-item', {active: active === item.id}]" @click="active = item.id; item.id === 'repairs' ? loadRepairs() : item.id === 'knowledge' && loadKnowledge()"><span class="nav-icon">{{ item.icon }}</span><span><b>{{ item.label }}</b><small>{{ item.desc }}</small></span></button></nav>
      <div class="sidebar-foot"><span class="online-dot"></span> 服务运行正常<br><small>数据保存在社区服务中心</small></div>
    </aside>

    <main class="content">
      <header class="topbar"><div><span class="eyebrow">{{ isAdmin ? 'ADMIN CONSOLE' : 'RESIDENT PORTAL' }}</span><h1>{{ active === 'assistant' ? '智能助手' : active === 'repairs' ? '报修工单' : '知识库扩展' }}</h1></div><div class="top-actions"><span v-if="notice" class="notice">{{ notice }}</span><span class="identity"><i :class="isAdmin ? 'admin-avatar' : 'user-avatar'">{{ isAdmin ? '管' : '住' }}</i>{{ isAdmin ? '物业管理员' : '小区住户' }}</span></div></header>

      <section v-if="active === 'assistant'" class="assistant-page"><div class="intro"><div><h2>今天需要什么帮助？</h2><p>查询社区公告、设施服务，或告诉我家中的问题，我会协助你创建报修工单。</p></div><span class="data-badge">● 已连接社区数据</span></div><div class="quick-grid"><button @click="quick('最近有什么社区公告？')"><b>社区公告</b><small>停水、安全与服务安排</small><span>→</span></button><button @click="quick('快递驿站在哪里，几点开放？')"><b>设施查询</b><small>位置、开放时间与服务内容</small><span>→</span></button><button @click="quick('我家厨房漏水，如何报修？')"><b>开始报修</b><small>描述问题，智能补全信息</small><span>→</span></button></div><section class="chat-panel"><div class="messages"><article v-for="(m,i) in messages" :key="i" :class="['bubble',m.role]"><span>{{ m.role === 'assistant' ? '邻里管家' : '我' }}</span><p>{{ m.content }}</p></article><div v-if="loading" class="loading"><i></i>正在查询社区服务数据...</div></div><div v-if="tools.length" class="tool-line">本轮已核验：<b v-for="t in tools" :key="t">{{ t }}</b></div><form @submit.prevent="send"><input v-model="input" placeholder="例如：我家卫生间漏水，想要报修"/><button>发送 <span>↵</span></button></form></section></section>

      <section v-else-if="active === 'repairs'" class="page-section"><div class="section-lead"><div><h2>{{ isAdmin ? '全部报修工单' : '我的报修工单' }}</h2><p>{{ isAdmin ? '管理员可查看、编辑和删除所有住户提交的工单。' : '这里展示你提交的工单；只有本人可以修改报修内容。' }}</p></div><button class="outline-button" @click="loadRepairs">刷新列表</button></div><div v-if="repairLoading" class="empty">正在加载工单...</div><div v-else-if="!repairs.length" class="empty"><strong>暂无报修工单</strong><span>在智能助手中描述问题即可发起报修。</span></div><div v-else class="repair-list"><article v-for="item in repairs" :key="item.id" class="repair-card"><div class="repair-head"><div><span class="order-id">{{ item.id }}</span><span :class="['status-pill', item.status === '已完成' ? 'done' : item.status === '处理中' ? 'working' : 'pending']">{{ item.status }}</span></div><time>{{ item.created_at?.slice(0,10) }}</time></div><div v-if="editing !== item.id" class="repair-body"><h3>{{ item.category }} · {{ item.location }}</h3><p>{{ item.description }}</p><div class="repair-meta"><span>联系人：{{ item.resident }}</span><span>电话：{{ item.phone }}</span><span>紧急程度：{{ item.urgency }}</span></div></div><div v-else class="edit-form"><input v-model="item.location" placeholder="位置"/><input v-model="item.category" placeholder="类别"/><textarea v-model="item.description" placeholder="问题描述"></textarea><select v-model="item.urgency"><option>普通</option><option>紧急</option></select><select v-if="isAdmin" v-model="item.status"><option>待受理</option><option>处理中</option><option>已完成</option><option>已取消</option></select></div><div class="repair-actions"><button v-if="canEdit(item) && editing !== item.id" @click="editing = item.id">编辑内容</button><button v-if="editing === item.id" class="primary" @click="updateRepair(item)">保存修改</button><button v-if="editing === item.id" @click="editing = null">取消</button><button v-if="isAdmin" class="danger" @click="removeRepair(item)">删除工单</button></div></article></div></section>

      <section v-else class="page-section"><div class="section-lead"><div><h2>知识库扩展</h2><p>资料会写入本地 Chroma 向量库，并保留来源和处理状态。</p></div><span class="data-badge">管理员权限</span></div><div class="knowledge-layout"><div class="knowledge-form"><label>资料名称<input v-model="knowledge.title" placeholder="例如：2026年物业服务手册"/></label><label>资料类型<select v-model="knowledge.source" @change="switchKnowledgeSource"><option value="text">文字内容</option><option value="pdf">PDF 文件</option><option value="url">网页地址</option></select></label><label>{{ knowledge.source === 'url' ? '网页地址' : knowledge.source === 'pdf' ? '选择 PDF 文件' : '资料内容' }}<input v-if="knowledge.source === 'pdf'" ref="knowledgeFile" type="file" accept="application/pdf,.pdf"/><input v-else-if="knowledge.source === 'url'" v-model="knowledge.content" type="url" placeholder="https://example.com/service"/><textarea v-else v-model="knowledge.content" rows="8" placeholder="粘贴物业制度、服务说明或公告内容"></textarea></label><button class="primary wide" :disabled="knowledgeLoading" @click="submitKnowledge">{{ knowledgeLoading ? '正在解析并写入向量库…' : '提交并建立索引' }}</button></div><div class="knowledge-info"><span class="info-icon">⌁</span><h3>资料处理状态</h3><p>文字、PDF 与网页正文会被切分并写入持久化向量索引。智能助手可依据索引内容回答物业知识问题。</p><div v-if="knowledgeDocs.length" class="knowledge-docs"><article v-for="doc in knowledgeDocs" :key="doc.id"><div class="knowledge-doc-head"><strong>{{ doc.title }}</strong><button class="knowledge-delete" title="删除资料及其索引" @click="removeKnowledge(doc)">删除</button></div><small>{{ doc.source_type }} · {{ doc.chunk_count }} 个片段 · {{ doc.status === 'ready' ? '已入库' : doc.status === 'failed' ? '失败' : '处理中' }}</small><small v-if="doc.error" class="knowledge-error">{{ doc.error }}</small></article></div><div v-else class="process"><span>暂无已入库资料</span></div></div></div></section>
    </main>
  </div>
</template>

<style>
:root{font-family:Inter,"Microsoft YaHei",sans-serif;color:#203b35;background:#f2f7f4;line-height:1.5}*{box-sizing:border-box}body{margin:0}.app-shell{min-height:100vh;display:flex}.sidebar{width:248px;background:#e4f1ea;border-right:1px solid #cfe1d7;padding:28px 18px 22px;display:flex;flex-direction:column}.brand{display:flex;align-items:center;gap:10px;padding:0 10px 34px}.brand-mark{display:grid;place-items:center;width:32px;height:32px;background:#2f8a70;color:white;border-radius:9px;font-size:24px;font-weight:300}.brand strong{display:block;font-size:17px;color:#174b3d}.brand small{display:block;font-size:9px;color:#63917f;letter-spacing:1.2px;margin-top:1px}.role-switch{display:grid;grid-template-columns:1fr 1fr;background:#d4e7dc;border-radius:8px;padding:4px;margin-bottom:24px}.role-switch span{grid-column:1/-1;font-size:11px;color:#6c8f7f;padding:3px 8px}.role-switch button{border:0;background:transparent;color:#5c7b6d;padding:7px;border-radius:6px;cursor:pointer}.role-switch button.selected{background:white;color:#24765e;box-shadow:0 1px 4px #bdd5c8}.nav-item{width:100%;display:flex;align-items:center;gap:12px;border:0;background:transparent;color:#4d7163;text-align:left;padding:12px 11px;margin:3px 0;border-radius:8px;cursor:pointer}.nav-item.active{background:#fff;color:#21785e;box-shadow:0 2px 10px #cde0d5}.nav-icon{font-size:20px;width:22px;text-align:center}.nav-item b{display:block;font-weight:600;font-size:14px}.nav-item small{display:block;color:#8aa697;font-size:11px;margin-top:1px}.nav-item.active small{color:#7baa96}.sidebar-foot{margin-top:auto;color:#568875;font-size:12px;padding:15px 10px;border-top:1px solid #ccdfd5;line-height:1.8}.sidebar-foot small{color:#87a999}.online-dot{display:inline-block;width:7px;height:7px;background:#38a878;border-radius:50%;margin-right:5px}.content{flex:1;min-width:0;padding:30px 42px;max-width:1440px}.topbar{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #d9e8df;padding-bottom:19px}.eyebrow{color:#5f9b84;font-size:10px;font-weight:700;letter-spacing:1.8px}.topbar h1{margin:5px 0 0;color:#214b3d;font-size:25px;letter-spacing:0}.top-actions{display:flex;align-items:center;gap:18px}.notice{color:#2a8064;font-size:12px;background:#e6f4ec;padding:7px 10px;border-radius:5px}.identity{display:flex;align-items:center;gap:8px;color:#527466;font-size:13px}.identity i{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;font-style:normal;font-size:12px}.user-avatar{background:#cde8d9;color:#277156}.admin-avatar{background:#dfe0c7;color:#77743a}.assistant-page,.page-section{max-width:1030px;margin:28px auto}.intro,.section-lead{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}.intro h2,.section-lead h2{font-size:22px;margin:0 0 5px;color:#234f40}.intro p,.section-lead p{margin:0;color:#749086;font-size:13px}.data-badge{font-size:12px;color:#398365;background:#e5f3eb;padding:7px 10px;border-radius:5px;white-space:nowrap}.quick-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:13px;margin-bottom:20px}.quick-grid button{position:relative;text-align:left;border:1px solid #d8e9df;background:#fbfefc;border-radius:9px;padding:17px 18px;color:#2a624f;cursor:pointer;min-height:90px}.quick-grid button:hover{border-color:#9bcbb1;background:#f6fcf8}.quick-grid b,.quick-grid small{display:block}.quick-grid b{font-size:14px}.quick-grid small{color:#86a296;font-size:11px;margin-top:5px}.quick-grid span{position:absolute;right:15px;bottom:13px;color:#55a27e}.chat-panel{background:#fff;border:1px solid #d9e9df;border-radius:10px;min-height:480px;display:flex;flex-direction:column;box-shadow:0 3px 14px #dfece4}.messages{padding:22px;flex:1;overflow:auto;max-height:430px}.bubble{max-width:74%;margin-bottom:16px;padding:11px 14px;border-radius:9px;line-height:1.65}.bubble span{font-size:11px;color:#82998f}.bubble p{white-space:pre-wrap;margin:3px 0 0;font-size:14px}.bubble.assistant{background:#eff8f2;border:1px solid #e0f0e5}.bubble.user{background:#2e8b70;color:#fff;margin-left:auto}.bubble.user span{color:#d9f2e4}.loading{color:#7e968a;font-size:12px}.loading i{display:inline-block;width:7px;height:7px;background:#42a87c;border-radius:50%;margin-right:6px}.tool-line{border-top:1px solid #edf3ef;padding:9px 22px;color:#81978c;font-size:11px}.tool-line b{color:#2d8969;margin-left:7px;font-weight:500}form{display:flex;gap:10px;padding:14px;border-top:1px solid #e7f0eb}input,textarea,select{font:inherit;border:1px solid #d1e2d8;background:#fbfefc;border-radius:6px;padding:10px;color:#34564a;outline:none}input:focus,textarea:focus,select:focus{border-color:#78b99a}form input{flex:1}button{font:inherit}.primary{background:#2d896c!important;color:white!important;border-color:#2d896c!important}.wide{width:100%;padding:12px}.outline-button,.repair-actions button{background:#fff;border:1px solid #c9dfd2;color:#3d8066;border-radius:5px;padding:8px 12px;cursor:pointer}.page-section{max-width:1030px}.repair-list{display:grid;gap:12px}.repair-card{background:white;border:1px solid #d9e9df;border-radius:9px;padding:17px 19px}.repair-head,.repair-meta,.repair-actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.order-id{font-size:12px;color:#50836f;font-weight:700;margin-right:9px}.status-pill{font-size:11px;padding:4px 8px;border-radius:20px;background:#f2eee0;color:#917e37}.status-pill.working{background:#e5f0f7;color:#537d98}.status-pill.done{background:#e1f3e8;color:#3b8a61}.repair-head time{font-size:11px;color:#9aada4}.repair-body h3{font-size:15px;margin:13px 0 5px;color:#315b4b}.repair-body p{font-size:13px;color:#688278;margin:0 0 10px}.repair-meta{justify-content:flex-start;flex-wrap:wrap;color:#8aa096;font-size:11px}.repair-actions{justify-content:flex-end;margin-top:14px}.repair-actions .danger{color:#aa655c;border-color:#e8ccc8}.edit-form{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:15px}.edit-form textarea{grid-column:1/-1;min-height:75px}.empty{min-height:300px;background:#fff;border:1px dashed #cfe3d7;border-radius:9px;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#82a093;gap:8px}.empty strong{color:#527f6c}.knowledge-layout{display:grid;grid-template-columns:1fr 1fr;gap:18px}.knowledge-form,.knowledge-info{background:#fff;border:1px solid #d9e9df;border-radius:9px;padding:22px}.knowledge-form label{display:block;color:#5b7e6f;font-size:12px;margin-bottom:14px}.knowledge-form input,.knowledge-form select,.knowledge-form textarea{width:100%;margin-top:6px}.knowledge-info{background:#edf7f0;color:#527f6c}.info-icon{font-size:30px;color:#3b966f}.knowledge-info h3{margin:8px 0;color:#285d4a;font-size:17px}.knowledge-info p{font-size:13px;line-height:1.8;color:#719387}.process{display:flex;flex-direction:column;gap:8px;margin-top:22px;color:#3a8869;font-size:12px}.process span{background:#fff;border-radius:5px;padding:9px}.knowledge-docs{display:grid;gap:8px;margin-top:14px}.knowledge-docs article{display:grid;gap:3px;background:#fff;padding:10px;border:1px solid #d9e9df;border-radius:5px}.knowledge-docs strong{font-size:12px;color:#315b4b}.knowledge-docs small{font-size:11px;color:#789186;overflow-wrap:anywhere}.knowledge-docs .knowledge-error{color:#aa655c}@media(max-width:800px){.sidebar{width:70px;padding:20px 9px}.brand div,.role-switch,.nav-item span:not(.nav-icon),.sidebar-foot{display:none}.brand{padding:0 10px 28px}.nav-item{justify-content:center}.content{padding:22px 16px}.quick-grid,.knowledge-layout{grid-template-columns:1fr}.topbar{align-items:flex-start}.identity{font-size:0}.intro,.section-lead{display:block}.data-badge{display:inline-block;margin-top:12px}}
</style>
