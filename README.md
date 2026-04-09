# K8s RAG Operations Assistant

一個**自我增強**的 Kubernetes 故障診斷系統。結合 RAG（Retrieval-Augmented Generation）、MCP（Model Context Protocol）和 LoRA Fine-Tune，透過 CLI 與 LLM 協作診斷 K8s 問題。每次診斷經驗自動回饋到知識庫，系統越用越聰明。

---

## 系統架構

```
┌─────────────────────────────────────────────────────┐
│                    OpenCode CLI                      │
│           (Terminal AI Agent, MCP Client)             │
└──────────┬──────────────┬──────────────┬────────────┘
           │              │              │
      MCP Protocol   MCP Protocol   OpenAI API
           │              │              │
┌──────────▼───┐  ┌───────▼──────┐  ┌───▼──────────┐
│  RAG MCP     │  │  K8s MCP     │  │  oMLX        │
│  Server      │  │  Server      │  │  Server      │
│  (Spring AI) │  │  (kubectl)   │  │  (本機 LLM)  │
│  Port: 8081  │  │  stdio       │  │  Port: 8000  │
└──────┬───────┘  └──────────────┘  └──────────────┘
       │
┌──────▼───────┐
│  PostgreSQL  │
│  + PGVector  │
│  Port: 5432  │
└──────────────┘
```

### 三大組件

| 組件 | 技術 | 功能 |
|------|------|------|
| **RAG MCP Server** | Spring Boot + Spring AI + PGVector | 文件匯入、語義檢索、診斷 session 管理、feedback 回饋循環 |
| **K8s MCP Server** | Python + MCP SDK | 封裝 kubectl 操作為 MCP tools（get, describe, logs, top, exec, events） |
| **Fine-Tune Pipeline** | Python + MLX LoRA | 從累積的診斷 sessions 訓練 LoRA adapter 增強模型行為 |

### 自我增強循環

```
使用者透過 OpenCode 診斷 K8s 問題
        ↓
OpenCode 呼叫 RAG MCP → 取得相關知識（runbooks + 過往經驗）
        ↓
OpenCode 呼叫 K8s MCP → 執行 kubectl 命令
        ↓
每步操作自動記錄到 Session（PostgreSQL）
        ↓
問題解決 → FeedbackService 自動：
  1. 將 session transcript 轉成結構化 runbook entry
  2. 用 LLM 生成摘要
  3. Embed 並存入 PGVector
        ↓
下次遇到類似問題 → RAG 自動檢索到這次經驗
        ↓
累積 200+ sessions → 觸發 LoRA Fine-Tune → 模型行為更精準
```

---

## 專案結構

```
llm-rag-tutroial/
├── backend/                         # Spring Boot RAG 後端
│   ├── pom.xml                      # Maven 依賴設定
│   ├── Dockerfile                   # 容器化建置
│   ├── models/all-MiniLM-L6-v2/     # ONNX embedding 模型 (384 維)
│   └── src/main/
│       ├── java/com/example/rag/
│       │   ├── RagApplication.java            # Spring Boot 入口
│       │   ├── config/RagConfig.java          # ChatClient + system prompt
│       │   ├── controller/
│       │   │   ├── RagController.java         # REST API
│       │   │   └── WebController.java         # Web UI
│       │   ├── mcp/RagMcpTools.java           # MCP tool 定義
│       │   ├── model/
│       │   │   ├── Session.java               # 診斷 session JPA entity
│       │   │   ├── Interaction.java           # 互動紀錄 JPA entity
│       │   │   ├── AskRequest.java            # 查詢 DTO
│       │   │   ├── AskResponse.java           # 回應 DTO
│       │   │   ├── DocumentInfo.java          # 文件資訊 DTO
│       │   │   └── IngestionResponse.java     # 匯入結果 DTO
│       │   ├── repository/
│       │   │   ├── SessionRepository.java     # Session DAO
│       │   │   └── InteractionRepository.java # Interaction DAO
│       │   └── service/
│       │       ├── RagService.java            # RAG 查詢 + 診斷
│       │       ├── DocumentIngestionService.java  # 文件匯入 + K8s metadata 偵測
│       │       ├── SessionService.java        # Session 生命週期管理
│       │       └── FeedbackService.java       # 回饋循環引擎（核心）
│       └── resources/
│           ├── application.yml                # 應用程式設定
│           └── templates/index.html           # Web UI
│
├── k8s-mcp-server/                  # K8s MCP Server
│   ├── server.py                    # MCP server 實作
│   └── requirements.txt             # Python 依賴
│
├── fine-tune/                       # Fine-Tune Pipeline
│   ├── configs/lora_config.yaml     # LoRA 超參數設定
│   ├── requirements.txt             # Python 依賴
│   └── scripts/
│       ├── export_training_data.py  # 從 DB 匯出訓練資料
│       ├── prepare_dataset.py       # 轉換為 MLX chat 格式
│       ├── train_lora.py            # LoRA fine-tune 訓練
│       └── evaluate.py              # 模型評估
│
├── docs/k8s-runbooks/               # 初始 RAG 知識庫
│   ├── pod-troubleshooting.md       # Pod 故障排除手冊
│   └── cluster-operations.md        # Cluster 維運手冊
│
├── opencode.yaml                    # OpenCode CLI 設定
├── docker-compose.yml               # 本地開發環境
└── .gitignore
```

---

## 前置需求

| 工具 | 版本 | 用途 |
|------|------|------|
| Java | 17+ | Spring Boot 後端 |
| Maven | 3.9+ | Java 建置 |
| Python | 3.10+ | K8s MCP Server + Fine-Tune |
| Docker + Docker Compose | latest | PostgreSQL + PGVector |
| oMLX | - | LLM 推論（運行於 `http://127.0.0.1:8000`） |
| kubectl | latest | K8s 操作（需已配置 kubeconfig） |
| OpenCode | latest | Terminal AI Agent CLI |

---

## 快速開始

### 1. 啟動 PostgreSQL（PGVector）

```bash
docker-compose up -d postgresql
```

驗證啟動：
```bash
docker-compose ps
# postgresql 狀態應為 healthy
```

### 2. 建置並啟動 Backend

```bash
cd backend
mvn clean package -DskipTests
mvn spring-boot:run
```

Backend 啟動後可透過瀏覽器存取 Web UI：http://localhost:8081

### 3. 安裝 K8s MCP Server 依賴

```bash
pip install -r k8s-mcp-server/requirements.txt
```

### 4. 匯入初始知識庫

透過 Web UI 上傳 `docs/k8s-runbooks/` 下的 Markdown 文件，或使用 API：

```bash
curl -F "file=@docs/k8s-runbooks/pod-troubleshooting.md" http://localhost:8081/api/documents/upload
curl -F "file=@docs/k8s-runbooks/cluster-operations.md" http://localhost:8081/api/documents/upload
```

### 5. 透過 OpenCode 使用

確保 oMLX 運行於 `http://127.0.0.1:8000`，然後：

```bash
opencode
```

OpenCode 會自動載入 `opencode.yaml`，連接 RAG MCP Server 和 K8s MCP Server。

---

## 使用方式

### Web UI

存取 http://localhost:8081，提供：

- **文件上傳**：拖放或選擇 PDF/TXT/MD/YAML 文件匯入知識庫
- **RAG 查詢**：輸入問題，系統從知識庫檢索相關內容後由 LLM 回答
- **直接查詢**：繞過 RAG，直接問 LLM（用於比較效果）

### REST API

| Method | Endpoint | 功能 |
|--------|----------|------|
| `POST` | `/api/documents/upload` | 上傳並匯入文件（multipart/form-data） |
| `GET` | `/api/documents` | 列出已匯入的文件 |
| `POST` | `/api/ask` | RAG 查詢 `{"question": "..."}` |
| `POST` | `/api/ask/simple` | 直接 LLM 查詢（無 RAG） |
| `POST` | `/api/diagnose` | K8s 診斷 `{"symptom": "...", "kubectlOutput": "..."}` |
| `POST` | `/feedback/process` | 批次處理未回饋的已解決 sessions |

### MCP Tools（透過 OpenCode 使用）

#### RAG MCP Server Tools

| Tool | 功能 | 範例 |
|------|------|------|
| `rag_query` | 語義搜尋知識庫 | `rag_query("pod stuck in Pending", category="ResourceQuota")` |
| `diagnose` | K8s 問題診斷 | `diagnose("OOMKilled in billing namespace", kubectlOutput="...")` |
| `session_start` | 開始診斷 session | `session_start("billing-api CrashLoopBackOff", "prod-cluster")` |
| `session_log` | 紀錄互動 | `session_log(sessionId, "KUBECTL_OUTPUT", "...")` |
| `session_resolve` | 結束 session | `session_resolve(sessionId, "RESOLVED", "increased memory limits")` |
| `ingest_content` | 匯入文字到知識庫 | `ingest_content("...", "runbook-oom-fix", "runbook")` |

#### K8s MCP Server Tools

| Tool | 功能 | 範例 |
|------|------|------|
| `kubectl_get` | 取得資源 | `kubectl_get(resource="pods", namespace="billing")` |
| `kubectl_describe` | 資源詳情 | `kubectl_describe(resource="pod", name="billing-api-xyz", namespace="billing")` |
| `kubectl_logs` | Pod 日誌 | `kubectl_logs(pod="billing-api-xyz", tail=50, previous=true)` |
| `kubectl_top` | 資源用量 | `kubectl_top(resource="pods", namespace="billing")` |
| `kubectl_exec` | 容器內執行命令 | `kubectl_exec(pod="billing-api-xyz", command="df -h")` |
| `kubectl_events` | 叢集事件 | `kubectl_events(namespace="billing")` |
| `kubectl_raw` | 任意 kubectl | `kubectl_raw(command="get pv --sort-by=.spec.capacity.storage")` |

---

## 診斷 Session 流程（自我增強核心）

一次完整的診斷 session 流程：

```
1. 使用者在 OpenCode 描述問題
   > "billing namespace 的 pod 一直 CrashLoopBackOff"

2. OpenCode 呼叫 session_start
   → 建立 session 紀錄

3. OpenCode 呼叫 rag_query 搜尋知識庫
   → 找到過往類似案例和 runbook

4. OpenCode 呼叫 kubectl_get、kubectl_describe、kubectl_logs
   → 取得即時叢集狀態

5. 每步操作由 OpenCode 呼叫 session_log 紀錄

6. LLM 根據 RAG 上下文 + kubectl 輸出提供診斷

7. 使用者確認修復後，OpenCode 呼叫 session_resolve("RESOLVED")
   → FeedbackService 自動將 session 轉成 runbook entry
   → 寫入 PGVector，下次可被檢索
```

### Session 互動類型

| Type | 說明 |
|------|------|
| `USER_QUERY` | 使用者提出的問題或描述 |
| `KUBECTL_COMMAND` | 執行的 kubectl 命令 |
| `KUBECTL_OUTPUT` | kubectl 命令的輸出結果 |
| `LLM_RESPONSE` | LLM 的診斷或建議 |
| `USER_ACTION` | 使用者執行的修復動作 |

---

## Fine-Tune Pipeline

當累積足夠的已驗證診斷 sessions 後，可透過 LoRA fine-tune 增強模型行為。

### 何時該 Fine-Tune（vs 只用 RAG）

| 情境 | RAG 夠用 | 需要 Fine-Tune |
|------|:--------:|:--------------:|
| 查詢已知故障解法 | V | |
| 結構化診斷思路（先看 events → logs → resources） | | V |
| 學習特定環境推理（我們用 Calico，網路問題先查 NetworkPolicy） | | V |
| 生成精確 kubectl 指令 | | V |
| 新故障模式即時可查 | V | |

### 執行步驟

```bash
cd fine-tune

# 1. 安裝依賴
pip install -r requirements.txt

# 2. 從 PostgreSQL 匯出訓練資料
python scripts/export_training_data.py ./data/training

# 3. 轉換為 MLX chat 格式（自動分割 train/valid/test）
python scripts/prepare_dataset.py ./data/training/training_data_*.jsonl ./data/dataset

# 4. 執行 LoRA fine-tune
python scripts/train_lora.py

# 5. 評估模型
python scripts/evaluate.py <model-name> ./adapters/k8s-ops-lora
```

### LoRA 設定（`fine-tune/configs/lora_config.yaml`）

```yaml
model: "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"
lora_rank: 16
lora_layers: 16
learning_rate: 1.0e-5
batch_size: 4
num_epochs: 3
```

Fine-tune 完成後，在 oMLX 載入 adapter 即可使用增強後的模型。

---

## 知識庫管理

### 支援的文件格式

| 格式 | 說明 |
|------|------|
| PDF | 技術文件、架構圖文件 |
| TXT | 純文字筆記、日誌片段 |
| Markdown | Runbooks、故障排除手冊 |
| YAML | K8s manifests、Helm charts |

### K8s Metadata 自動偵測

匯入文件時，系統自動偵測以下 metadata 並標記，用於過濾檢索：

- `k8s.resource.kind`：Pod、Deployment、Service
- `incident.category`：OOMKill、CrashLoopBackOff、ResourceQuota、Network、ImagePull、NodePressure

### 預載知識庫

專案內含兩份 K8s runbook：

- `docs/k8s-runbooks/pod-troubleshooting.md` — CrashLoopBackOff、Pending、OOMKilled、ImagePullBackOff
- `docs/k8s-runbooks/cluster-operations.md` — Node NotReady、網路問題、憑證過期、etcd 問題

---

## 設定說明

### Backend（`backend/src/main/resources/application.yml`）

| 設定 | 預設值 | 說明 |
|------|--------|------|
| `spring.datasource.url` | `jdbc:postgresql://localhost:5432/ragdb` | PostgreSQL 連線 |
| `spring.ai.openai.base-url` | `http://127.0.0.1:8000` | oMLX LLM endpoint |
| `spring.ai.vectorstore.pgvector.dimensions` | `384` | Embedding 維度（配合 all-MiniLM-L6-v2） |
| `server.port` | `8081` | Backend HTTP port |

### OpenCode（`opencode.yaml`）

| 設定 | 說明 |
|------|------|
| `providers.omlx.baseURL` | oMLX server 位址 |
| `mcpServers.rag` | RAG MCP Server（需先啟動 backend） |
| `mcpServers.k8s` | K8s MCP Server（需安裝 Python MCP SDK） |

---

## Docker 部署

### 本地開發（僅 PostgreSQL）

```bash
docker-compose up -d postgresql
cd backend && mvn spring-boot:run
```

### 完整容器化

```bash
docker-compose up -d
```

> 注意：backend 容器透過 `host.docker.internal:8000` 連接 host 上的 oMLX。

---

## 技術細節

### Embedding 模型

- **模型**：all-MiniLM-L6-v2（ONNX 格式）
- **維度**：384
- **執行**：本機 in-process，無需 GPU 或外部 API
- **位置**：`backend/models/all-MiniLM-L6-v2/`

### Vector Store

- **引擎**：PostgreSQL 16 + pgvector 擴充
- **索引**：HNSW（Hierarchical Navigable Small World）
- **距離函數**：Cosine Distance
- **優勢**：支援 metadata 過濾、生產級持久化、併發存取

### RAG Pipeline

1. **文件匯入** → `DocumentIngestionService` 解析文件
2. **分塊** → `TokenTextSplitter` 以 token 為單位切割
3. **Metadata 標記** → 自動偵測 K8s 資源類型和故障類別
4. **向量化** → all-MiniLM-L6-v2 生成 384 維 embedding
5. **儲存** → PGVector 持久化
6. **檢索** → `VectorStoreDocumentRetriever` 語義搜尋 + metadata 過濾（top-K=5）
7. **增強** → `RetrievalAugmentationAdvisor` 將檢索結果注入 LLM prompt
8. **回應** → LLM 基於上下文生成診斷

### MCP 協定

MCP（Model Context Protocol）是 Anthropic 提出的標準化協定，讓 LLM 透過結構化介面存取外部工具。本專案使用 MCP 作為膠合層：

- **RAG MCP Server**：Spring AI 的 `@Tool` 註解暴露 Java 方法為 MCP tools
- **K8s MCP Server**：Python MCP SDK 封裝 kubectl 命令
- **傳輸**：stdio（本地）或 HTTP（遠端部署）

---

## 擴展方向

### Phase 2: Remote MCP on K8s

在 K8s cluster 內部署 MCP Server，提供集中化的 kubectl 操作入口：

```
OpenCode → Ingress → MCP Gateway Pod → kubectl (ServiceAccount RBAC)
```

優點：統一 audit、多人共用、集中化權限管理。

### 整合更多資料來源

- PagerDuty / OpsGenie 事件
- Prometheus 告警
- Grafana dashboard 連結
- Jira / Linear ticket

### 生產部署

以 Helm Chart 打包，包含：

- Backend Deployment (2+ replicas)
- PostgreSQL StatefulSet (PGVector)
- vLLM Deployment (GPU node，替代本機 oMLX)
- MCP Server Deployment
- Ingress + NetworkPolicy
