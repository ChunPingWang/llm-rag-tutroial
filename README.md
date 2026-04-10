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

## 技術棧與原理

### 後端框架層

| 技術 | 版本 | 角色 | 原理 |
|------|------|------|------|
| **Spring Boot** | 3.4.1 | 應用程式框架 | 依賴注入、REST API、Actuator 監控。簡化企業級應用開發 |
| **Spring AI** | 1.0.0 | AI 整合框架 | 抽象化 LLM、Embedding、VectorStore。`ChatClient` 統一介面支援多家 LLM provider；`RetrievalAugmentationAdvisor` 自動將 RAG 上下文注入 prompt |
| **Spring Data JPA** | - | ORM | 管理 Session/Interaction entities，自動產生 DDL，提供 Repository pattern |
| **Maven** | 3.9+ | 建置工具 | 依賴管理與打包 |

### 向量資料庫層（RAG 核心）

| 技術 | 版本 | 角色 | 原理 |
|------|------|------|------|
| **PostgreSQL** | 16 | 關聯式資料庫 | 儲存 Session 紀錄 + 向量資料（同一個 DB 雙用途） |
| **pgvector** | latest | PostgreSQL 向量擴充 | 將向量運算下推到 DB 層，支援 SQL + 向量混合查詢（例如：WHERE metadata->>'category'='OOMKill' ORDER BY embedding <=> query） |
| **HNSW Index** | - | 近似最近鄰搜尋演算法 | Hierarchical Navigable Small World — 多層圖結構，上層稀疏快速導航、下層密集精確搜尋。查詢複雜度 O(log N)，記憶體換取速度 |
| **Cosine Distance** | - | 向量相似度度量 | `1 - (A·B) / (|A|·|B|)`。只關心向量方向不關心長度，適合文本 embedding（文本長度不應影響語義相似度） |

**為什麼選 PGVector 而不是 Pinecone/Weaviate/Milvus？**
- 已有 PostgreSQL 用於 session 紀錄，避免新增基礎設施
- ACID 交易保證向量資料和 metadata 一致
- SQL 過濾能力強（`WHERE metadata->>'incident.category' = 'OOMKill'`）
- 本地部署，無資料外流風險，適合機房環境
- HNSW 性能接近專用向量 DB（<100ms 延遲 for <1M vectors）

### Embedding 模型層

| 技術 | 細節 | 原理 |
|------|------|------|
| **all-MiniLM-L6-v2** | Sentence-Transformers 模型 | 由 BERT 蒸餾而來的輕量語義模型。6 層 Transformer，22M 參數，訓練於 1B+ 句對 |
| **ONNX Runtime** | 執行引擎 | 將 PyTorch 模型轉為 ONNX 格式，純 Java 執行（無需 Python）。推論速度比原生 PyTorch 快 1.5-2x |
| **384 維向量** | Embedding 輸出 | 每個文本片段壓縮為 384 個浮點數，保留語義資訊。維度越高越精準但越耗空間 |
| **Token-based Splitter** | Spring AI 內建 | 以 token 為單位切割文件（非字元），避免切斷語義邊界 |

**Embedding 原理**：文本 → tokenize → Transformer 編碼 → 取 [CLS] token 的隱藏狀態 → L2 normalize → 384 維向量。語義相近的文本在向量空間中距離也相近。

### LLM 推論層

| 技術 | 角色 | 原理 |
|------|------|------|
| **oMLX** | 本機 LLM 服務 | Apple MLX 框架的推論 server，原生支援 Apple Silicon 的 Metal GPU 加速。OpenAI-compatible API |
| **OpenAI Protocol** | 通訊協定 | `/v1/chat/completions` 標準介面，Spring AI 可無縫對接任何相容的 provider（LM Studio、vLLM、Ollama、oMLX） |
| **System Prompt** | Prompt Engineering | 定義 LLM 的角色（K8s SRE 專家）和行為（先分析、再建議命令、再診斷） |
| **LoRA (Low-Rank Adaptation)** | Fine-Tune 技術 | 凍結基礎模型權重，只訓練兩個低秩矩陣 A、B，`W' = W + BA`。參數量減少 10000 倍，可在單張消費級 GPU 上訓練 |

**RAG vs Fine-Tune 原理比較**：
- **RAG**：不改變模型，在推論時將檢索到的文件拼接到 prompt。優點：即時更新、可引用來源、成本低
- **Fine-Tune**：修改模型權重，讓模型「記住」知識。優點：推論時不需要檢索、回答風格一致
- **最佳實踐**：RAG 處理事實類知識（80%），Fine-Tune 處理行為模式和推理風格（20%）

### CLI 與協定層

| 技術 | 角色 | 原理 |
|------|------|------|
| **OpenCode** | Terminal AI Agent | 原生支援 MCP client 和 OpenAI API。提供 chat UI、檔案操作、工具呼叫 |
| **MCP (Model Context Protocol)** | Anthropic 標準協定 | 類似「LLM 的 Language Server Protocol」。讓 LLM 透過結構化介面呼叫工具，統一 tool discovery 和 invocation |
| **stdio Transport** | MCP 傳輸層 | 透過程序的 stdin/stdout 通訊（JSON-RPC）。優點：本地部署無網路開銷、安全 |
| **kubectl + client-go** | K8s 操作介面 | 透過 kubeconfig 存取 cluster，使用使用者自己的 RBAC 權限（最小權限原則） |

### RAG 完整流程原理

```
[文件匯入階段]
文件 (PDF/MD/YAML) 
  → TextReader 解析 
  → TokenTextSplitter 切塊（預設 800 tokens/chunk） 
  → all-MiniLM-L6-v2 編碼為 384 維向量 
  → 加上 metadata（source, category, kind） 
  → PGVector INSERT

[查詢階段]
使用者問題 
  → 同一個 embedding 模型編碼為 384 維向量 
  → pgvector HNSW 索引找最近的 K 個向量（cosine distance） 
  → 過濾 similarity > threshold 且 metadata 符合條件 
  → 取出對應的文字 chunks 
  → 組成 context prompt 
  → 送給 LLM 生成回答

[回饋階段]
Session 結束並標記 RESOLVED 
  → FeedbackService 合成 transcript 
  → LLM 生成結構化 runbook entry 
  → 重新 embed 並寫入 PGVector 
  → 偵測 incident.category 作為 metadata 
  → 下次查詢時可被檢索
```

### 監控與維運層

| 技術 | 用途 |
|------|------|
| **Spring Boot Actuator** | Health check、metrics、環境變數 endpoint |
| **Docker Compose** | 本地開發環境編排（PostgreSQL + Backend） |
| **SLF4J + Logback** | 結構化日誌 |

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

## 評估框架

完整的 RAG + Fine-Tune 評估系統，量化系統效果與正確性。

### 評估架構

```
eval/
├── datasets/
│   ├── k8s_eval_dataset.json          # 40 個 RAG 測試案例（8 類別）
│   └── k8s_diagnose_dataset.json      # 10 個 diagnose 測試案例
├── lib/
│   ├── metrics.py                     # 指標計算（recall, coverage, hallucination）
│   ├── kubectl_parser.py              # kubectl 命令正則提取與危險命令偵測
│   ├── llm_judge.py                   # LLM-as-Judge 評分（4 維度 1-5 分）
│   └── report_generator.py            # 終端表格 + JSON 報告產生器
├── rag_evaluator.py                   # RAG 品質評估
├── finetune_evaluator.py              # Fine-Tune 前後對比
├── rag_parameter_sweep.py             # 參數掃描（threshold × topK）
├── e2e_evaluator.py                   # 端到端 feedback loop 驗證
├── run_all.sh                         # 一鍵執行全部評估
└── reports/                           # 輸出報告目錄
```

### 評估指標

| 指標 | 目標 | 計算方式 | 適用 |
|------|------|---------|------|
| **Retrieval Keyword Recall** | ≥0.7 | 回答中命中 expected_retrieval_keywords 的比例 | RAG |
| **Answer Keyword Coverage** | ≥0.6 | 回答中命中 expected_answer_keywords 的比例 | RAG + FT |
| **Command Recall** | ≥0.5 | 提取的 kubectl 命令 vs expected（模糊比對） | RAG + FT |
| **Hallucination Score** | ≥0.95 | 1 − (危險命令數 / 總命令數) | RAG + FT |
| **Structure Score** | ≥0.6 | 回答含 Root Cause/Diagnosis/Resolution 等結構 | FT |
| **LLM-as-Judge (1-5)** | ≥3.5 | oMLX 評分 correctness/completeness/safety/actionability | RAG + FT |
| **RAG Lift** | >0 | RAG 分數 − No-RAG 分數 | RAG |
| **Feedback Improvement** | >0 | 回饋後分數 − 回饋前分數 | E2E |

### 評估類型

#### 1. RAG 評估（`rag_evaluator.py`）

對 40 個 ground truth 問題逐一測試：
- 呼叫 `/api/ask`（RAG）和 `/api/ask/simple`（無 RAG）
- 計算 5 大指標
- 比較 RAG vs No-RAG 的差距（RAG Lift）
- 按類別分組報告（OOMKill、CrashLoopBackOff、Network…）

```bash
python eval/rag_evaluator.py --base-url http://localhost:8081
python eval/rag_evaluator.py --llm-judge  # 啟用 LLM-as-Judge
```

#### 2. Fine-Tune 評估（`finetune_evaluator.py`）

對比基礎模型與 LoRA fine-tuned 模型：
- 透過 oMLX OpenAI-compatible API 推論（不直接呼叫 mlx_lm，確保與生產路徑一致）
- 計算相同指標集
- 產生 base vs fine-tuned 對比表

```bash
# 只評估基礎模型
python eval/finetune_evaluator.py --base-url http://127.0.0.1:8000

# 對比 base vs fine-tuned
python eval/finetune_evaluator.py \
  --base-url http://127.0.0.1:8000 \
  --adapter-url http://127.0.0.1:8001
```

#### 3. 參數掃描（`rag_parameter_sweep.py`）

自動測試 5 × 4 = 20 種 (threshold, topK) 組合：
- threshold: 0.1, 0.2, 0.3, 0.4, 0.5
- topK: 3, 5, 8, 10
- 加上 category filter 開關對比
- 以加權 composite score 找出最佳配置

```bash
python eval/rag_parameter_sweep.py --sample-size 10
```

#### 4. 端到端 Feedback Loop 評估（`e2e_evaluator.py`）

驗證自我增強機制是否真的有效：
1. **Baseline**：對 3 個「新知識」問題評分（系統應該答不好）
2. **Inject**：注入合成的 resolved session（例如：Hikari connection pool leak 的診斷經驗）
3. **Post-feedback**：重新評分（系統應該答得更好）
4. **Delta**：量化改進幅度

```bash
python eval/e2e_evaluator.py --base-url http://localhost:8081
```

### 一鍵執行全部評估

```bash
# 前置：確保 backend 和 oMLX 都在運行
cd backend && mvn spring-boot:run &
# oMLX 應已跑在 127.0.0.1:8000

pip install -r eval/requirements.txt
bash eval/run_all.sh
```

輸出範例：

```
==============================================
  RAG Evaluation Framework
==============================================
  [1/40] oom-001: My pod keeps getting killed with exit code 137...
  [2/40] clb-001: My pod keeps showing CrashLoopBackOff status...
  ...

+----------------------------+--------+--------+--------+----------+--------+
|          Metric            |  Mean  |  Min   |  Max   |  Target  | Status |
+----------------------------+--------+--------+--------+----------+--------+
|  retrieval_keyword_recall  | 0.752  | 0.500  | 1.000  |  >=0.7   |  PASS  |
|  answer_keyword_coverage   | 0.683  | 0.333  | 1.000  |  >=0.6   |  PASS  |
|  command_recall            | 0.575  | 0.000  | 1.000  |  >=0.5   |  PASS  |
|  hallucination_score       | 0.985  | 0.900  | 1.000  |  >=0.95  |  PASS  |
|  structure_score           | 0.712  | 0.400  | 1.000  |  >=0.6   |  PASS  |
+----------------------------+--------+--------+--------+----------+--------+

--- RAG Lift Analysis ---
  Average RAG Lift: +0.187
  RAG Better: 32/40 (80%)
  Verdict: RAG IS HELPING
```

### 使用情境

- **系統驗收**：部署前確認 RAG 品質達標
- **回歸測試**：每次更新 runbook 或模型後執行，確保沒有退化
- **參數調校**：透過 sweep 找出最佳 threshold/topK
- **Fine-Tune 決策**：量化 fine-tune 帶來的實際效益
- **Feedback Loop 驗證**：證明自我增強機制有效

### 擴展評估資料集

在 `eval/datasets/k8s_eval_dataset.json` 加入新案例即可：

```json
{
  "id": "new-001",
  "category": "NewCategory",
  "question": "你的問題",
  "expected_retrieval_keywords": ["keyword1", "keyword2"],
  "expected_answer_keywords": ["concept1", "concept2"],
  "expected_kubectl_commands": ["kubectl get ..."],
  "ground_truth_summary": "預期回答摘要",
  "difficulty": "easy|medium|hard"
}
```

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
