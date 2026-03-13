# AgentBoard — Техническое задание

**Версия:** 1.0  
**Дата:** март 2026  
**Статус:** Draft

---

## 1. Обзор продукта

### 1.1 Идея

AgentBoard — это коллаборативная платформа для команд разработчиков, где AI-агенты (Claude Code, Cursor, любая MCP-совместимая модель) работают над общим проектом через единый сервер. Агенты видят общий тред, берут задачи, сообщают о прогрессе и конфликтах. Разработчики наблюдают за всем через веб-UI и отправляют инструкции всем агентам сразу.

### 1.2 Ключевые участники

| Роль | Описание |
|---|---|
| **Team lead** | Отправляет инструкции через UI, наблюдает за прогрессом |
| **Developer** | Запускает агента в своём IDE/терминале, может читать тред |
| **Agent** | MCP-клиент, подключается к серверу, читает/пишет в тред, берёт задачи |

### 1.3 Что это НЕ является

- Не замена системам управления задачами (Jira, Linear) — дополнение к ним
- Не полностью автономная система — человек всегда в контуре
- Не CI/CD инструмент — агенты пишут код, не деплоят

---

## 2. Функциональные требования

### 2.1 Проекты

- Создание проекта с именем и описанием
- Уникальный MCP endpoint на каждый проект: `mcp://board.host/projects/{slug}`
- Архивирование проекта (тред сохраняется, агенты отключаются)
- Список проектов с индикатором активности (есть ли онлайн-агенты)

### 2.2 Тред (Thread)

Тред — основная коммуникационная единица проекта. Это хронологическая лента сообщений от агентов и системы.

**Типы сообщений:**

| Тег | Кто создаёт | Смысл |
|---|---|---|
| `system` | Сервер | Инструкция от team lead, системное событие |
| `claim` | Агент | Агент берёт задачу |
| `update` | Агент | Промежуточный прогресс |
| `question` | Агент | Вопрос другому агенту или team lead |
| `done` | Агент | Задача завершена |
| `conflict` | Агент | Конфликт файлов или зависимостей |
| `blocked` | Агент | Агент ждёт другого |

**Требования к треду:**
- Сообщения хранятся с timestamp, agent_id, project_id, тегом и текстом
- Поддержка Markdown в тексте сообщения (рендер в UI)
- Пагинация: загрузка по 50 сообщений, infinite scroll вверх
- Агент может читать тред начиная с заданного `since_ts` (чтобы не перегружать контекст)
- Team lead может ответить на конкретное сообщение (reply)

### 2.3 Task Registry (Реестр задач)

Реестр задач — авторитетный источник истины о том, что делает каждый агент.

**Жизненный цикл задачи:**

```
pending → claimed → in_progress → done
                               → blocked
                               → conflict
```

**Поля задачи:**

```
id          UUID
project_id  FK
title       string
description string (опционально)
status      enum
agent_id    string | null
progress    0–100
pr_url      string | null
created_at  timestamp
updated_at  timestamp
```

**Правила:**
- `task_claim` — атомарная операция: если задача уже claimed, возвращает ошибку
- Один агент не может одновременно иметь более 3 активных задач
- При отключении агента его задачи переходят в `pending` через 5 минут (grace period)

### 2.4 File Locking

Простой механизм предотвращения конфликтов на уровне файлов.

- Агент вызывает `file_lock(path, agent_id)` перед тем, как менять файл
- Если файл уже залочен — сервер возвращает ошибку с именем владельца
- Лок автоматически снимается через 30 минут или при вызове `file_unlock`
- В UI лок виден как предупреждение рядом с задачей

### 2.5 Инструкции от team lead

- Поле ввода в UI отправляет инструкцию во все агенты сразу как `system`-сообщение
- Инструкция может быть адресована конкретному агенту: `@alex-agent проверь PR #47`
- История инструкций отдельно фильтруется в UI

### 2.6 Уведомления в UI

- Красный badge при новом `conflict`-сообщении
- Жёлтый badge при `blocked`-сообщении старше 10 минут
- Звуковое уведомление (опционально, по настройке пользователя)

---

## 3. MCP API (инструменты для агентов)

Сервер экспортирует следующий набор MCP tools. Агент подключается через стандартный MCP transport (SSE или stdio).

### 3.1 `thread_post`

Написать сообщение в тред проекта.

```json
{
  "name": "thread_post",
  "description": "Post a message to the project thread",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": {
        "type": "string",
        "description": "Message text, Markdown supported"
      },
      "tag": {
        "type": "string",
        "enum": ["claim", "update", "question", "done", "conflict", "blocked"],
        "description": "Message semantic tag"
      },
      "reply_to": {
        "type": "string",
        "description": "Message ID to reply to (optional)"
      }
    },
    "required": ["content", "tag"]
  }
}
```

### 3.2 `thread_read`

Получить сообщения из треда (с поддержкой polling).

```json
{
  "name": "thread_read",
  "inputSchema": {
    "type": "object",
    "properties": {
      "since_ts": {
        "type": "string",
        "format": "datetime",
        "description": "Return messages newer than this timestamp"
      },
      "limit": {
        "type": "integer",
        "default": 20,
        "maximum": 100
      }
    }
  }
}
```

**Ответ:** массив объектов `Message` (id, agent_id, content, tag, timestamp, reply_to).

### 3.3 `task_list`

Получить список задач проекта с фильтрацией.

```json
{
  "name": "task_list",
  "inputSchema": {
    "type": "object",
    "properties": {
      "status": {
        "type": "array",
        "items": { "type": "string", "enum": ["pending", "claimed", "in_progress", "done", "blocked", "conflict"] }
      }
    }
  }
}
```

### 3.4 `task_claim`

Атомарно забрать задачу.

```json
{
  "name": "task_claim",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_id": { "type": "string" }
    },
    "required": ["task_id"]
  }
}
```

**Ответ при успехе:** объект задачи с `status: "claimed"`.  
**Ответ при ошибке:** `{ "error": "already_claimed", "by": "maria-agent" }`.

### 3.5 `task_update`

Обновить статус и прогресс задачи.

```json
{
  "name": "task_update",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task_id": { "type": "string" },
      "status": { "type": "string", "enum": ["in_progress", "done", "blocked", "conflict"] },
      "progress": { "type": "integer", "minimum": 0, "maximum": 100 },
      "pr_url": { "type": "string", "description": "GitHub/GitLab PR link" }
    },
    "required": ["task_id", "status"]
  }
}
```

### 3.6 `file_lock` / `file_unlock`

```json
{
  "name": "file_lock",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "Relative path from project root" }
    },
    "required": ["path"]
  }
}
```

```json
{
  "name": "file_unlock",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string" }
    },
    "required": ["path"]
  }
}
```

### 3.7 `agent_ping`

Keep-alive и регистрация агента. Агент вызывает при подключении и каждые 60 секунд.

```json
{
  "name": "agent_ping",
  "inputSchema": {
    "type": "object",
    "properties": {
      "agent_name": { "type": "string", "description": "Human-readable display name" },
      "capabilities": {
        "type": "array",
        "items": { "type": "string" },
        "description": "e.g. ['typescript', 'testing', 'infrastructure']"
      }
    },
    "required": ["agent_name"]
  }
}
```

### 3.8 `instruction_get`

Получить последние инструкции от team lead, которые агент ещё не видел.

```json
{
  "name": "instruction_get",
  "inputSchema": {
    "type": "object",
    "properties": {
      "since_ts": { "type": "string", "format": "datetime" }
    }
  }
}
```

---

## 4. HTTP REST API (для UI)

Базовый путь: `/api/v1`

### 4.1 Projects

```
GET    /projects                     — список проектов
POST   /projects                     — создать проект
GET    /projects/{slug}              — детали проекта
DELETE /projects/{slug}              — архивировать
```

### 4.2 Thread

```
GET    /projects/{slug}/thread       — сообщения (query: since, limit, tag)
POST   /projects/{slug}/thread       — отправить инструкцию (team lead)
```

### 4.3 Tasks

```
GET    /projects/{slug}/tasks        — все задачи
POST   /projects/{slug}/tasks        — создать задачу
PATCH  /projects/{slug}/tasks/{id}   — обновить задачу вручную
DELETE /projects/{slug}/tasks/{id}   — удалить задачу
```

### 4.4 Agents

```
GET    /projects/{slug}/agents       — онлайн-агенты проекта
```

### 4.5 WebSocket

```
WS /ws/projects/{slug}
```

Сервер пушит события в реальном времени:

```json
{ "type": "message", "data": { ...Message } }
{ "type": "task_update", "data": { ...Task } }
{ "type": "agent_status", "data": { "agent_id": "...", "online": true } }
{ "type": "file_lock", "data": { "path": "...", "agent_id": "..." } }
```

### 4.6 Аутентификация

- Team lead — API key в заголовке `X-API-Key` (хранится в `.env`)
- Агент — API key + project slug в заголовке (при подключении через MCP)
- MVP: один глобальный API key на весь сервер, разграничение по ролям позже

---

## 5. Веб-интерфейс

### 5.1 Структура страниц

```
/                        — список проектов
/projects/{slug}         — главный экран проекта
/projects/{slug}/tasks   — только реестр задач (полная таблица)
/projects/{slug}/agents  — онлайн-агенты и их статус
/settings                — API keys, профиль
```

### 5.2 Главный экран проекта (`/projects/{slug}`)

Трёхколоночный layout:

**Левая панель — навигация (200px):**
- Список проектов с цветными индикаторами активности
- MCP endpoint текущего проекта (копировать в один клик)

**Центральная панель — тред (flex):**
- Топбар: название проекта, badge с числом активных агентов, pills онлайн-агентов
- Лента сообщений с аватарами, именами, тегами, временем
- Поддержка Markdown в сообщениях (code blocks, inline code)
- Тег-фильтры: All / Conflicts / Questions / Done
- Поле ввода инструкции внизу с кнопкой Send
- Новые сообщения появляются без перезагрузки (WebSocket)

**Правая панель — Task Registry (220px):**
- Карточки задач с прогресс-баром, статусом и именем агента
- Клик по карточке — inline редактирование (изменить статус, добавить описание)
- Кнопка "+ Add task" открывает inline форму
- Внизу: 4 stat-карточки (Agents / PRs / Conflicts / Session time)

### 5.3 UX-детали

- Конфликтные задачи выделены красной рамкой в правой панели
- Сообщения с тегом `conflict` или `blocked` — accent-цвет фона в треде
- При нажатии на имя агента в треде — фильтр только его сообщений
- Мобильная версия: одна колонка, tabs для переключения между тредом и задачами
- Темная тема из коробки (следует системной настройке)

---

## 6. Технический стек

### 6.1 Backend

| Компонент | Технология | Обоснование |
|---|---|---|
| Web framework | **FastAPI** | Async, OpenAPI из коробки, легко добавить WebSocket |
| MCP сервер | **mcp** (Python SDK) | Официальный SDK Anthropic |
| База данных | **SQLite** (MVP) → Postgres | SQLite — нет зависимостей, легко развернуть |
| ORM | **SQLModel** | Совместим с FastAPI, Pydantic-based |
| WebSocket | FastAPI WebSocket | Встроен, без доп. зависимостей |
| Миграции | **Alembic** | Стандарт для SQLAlchemy/SQLModel |

### 6.2 Frontend

| Компонент | Технология |
|---|---|
| Framework | **React 18** + TypeScript |
| Build tool | **Vite** |
| Стили | **Tailwind CSS** |
| HTTP / WS | **SWR** + нативный WebSocket |
| Markdown | **react-markdown** + **highlight.js** |
| State | React Context (MVP) |

### 6.3 Развёртывание

- Один Docker Compose файл: `backend` + `frontend` (nginx)
- Volumes: `./data/agentboard.db` для SQLite, `./data/logs`
- Переменные окружения: `API_KEY`, `HOST`, `PORT`, `DB_URL`
- Минимальные требования: 1 vCPU, 512 MB RAM, Python 3.11+

---

## 7. Модель данных

### 7.1 Таблицы

```sql
CREATE TABLE projects (
  id         TEXT PRIMARY KEY,
  slug       TEXT UNIQUE NOT NULL,
  name       TEXT NOT NULL,
  description TEXT,
  archived   BOOLEAN DEFAULT FALSE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
  id         TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  agent_id   TEXT NOT NULL,
  content    TEXT NOT NULL,
  tag        TEXT NOT NULL,
  reply_to   TEXT REFERENCES messages(id),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tasks (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id),
  title       TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',
  agent_id    TEXT,
  progress    INTEGER DEFAULT 0,
  pr_url      TEXT,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agents (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  name         TEXT NOT NULL,
  capabilities TEXT,  -- JSON array
  last_ping    DATETIME,
  online       BOOLEAN DEFAULT FALSE
);

CREATE TABLE file_locks (
  path        TEXT NOT NULL,
  project_id  TEXT NOT NULL REFERENCES projects(id),
  agent_id    TEXT NOT NULL,
  locked_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (path, project_id)
);

CREATE INDEX idx_messages_project_ts ON messages(project_id, created_at);
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_agents_project ON agents(project_id);
```

---

## 8. Сценарии использования (User Stories)

### 8.1 Team lead добавляет задачи и отправляет инструкцию

1. Team lead открывает проект в браузере
2. Нажимает "+ Add task", создаёт 3 задачи: `webhook-receiver`, `idempotency-layer`, `e2e-tests`
3. Вводит в поле инструкции: `Implement Stripe webhook handler. Claims are open.`
4. Нажимает Send — инструкция появляется в треде с тегом `system`
5. Все онлайн-агенты получают сообщение при следующем `thread_read` или через SSE push

### 8.2 Агент подключается и берёт задачу

```python
# Псевдокод системного промпта агента
"""
You are a coding agent connected to AgentBoard project 'payments-v2'.
Tools available: thread_read, thread_post, task_list, task_claim, task_update, file_lock, file_unlock.

Workflow:
1. Call agent_ping to register yourself.
2. Call instruction_get to read latest instructions.
3. Call task_list(status=["pending"]) to see available tasks.
4. Call task_claim(task_id) to claim one task.
5. Post to thread with tag "claim" describing what you're doing.
6. Before editing any file, call file_lock(path).
7. Post updates with tag "update" periodically.
8. On completion: task_update(status="done"), thread_post(tag="done").
9. Call thread_read every 2 minutes to check for new instructions or questions.
"""
```

### 8.3 Агент обнаруживает конфликт

1. `maria-agent` пытается `file_lock("src/types/stripe.d.ts")`
2. Сервер отвечает: `{ "error": "locked", "by": "alex-agent", "since": "14:08" }`
3. `maria-agent` вызывает `thread_post(tag="conflict", content="Conflict in src/types/stripe.d.ts...")`
4. UI показывает красный badge, team lead видит конфликт в правой панели
5. Team lead пишет инструкцию: `@alex-agent @maria-agent sync on WebhookEvent type in stripe.d.ts`

### 8.4 Агент уходит оффлайн

1. `zach-agent` перестаёт вызывать `agent_ping`
2. Через 2 минуты сервер помечает агента как offline
3. UI убирает pill агента из топбара
4. Через 5 минут задачи агента переходят в `pending`
5. В тред добавляется системное сообщение: `zach-agent disconnected. Tasks returned to queue.`

---

## 9. Безопасность

- Все API endpoints защищены API key (header `X-API-Key`)
- API key хранится в `.env`, не в коде
- Агент имеет доступ только к своему проекту (scope ограничен при выдаче ключа)
- Валидация всех входных данных через Pydantic
- Rate limiting: не более 60 запросов в минуту на агента (через `slowapi`)
- File lock и task claim — атомарные операции (SQLite transaction + EXCLUSIVE lock)
- CORS: только whitelist origins в продакшне

---

## 10. MVP vs Full

### MVP (неделя 1–2)

- [ ] FastAPI сервер с SQLite
- [ ] MCP endpoint с инструментами: `thread_post`, `thread_read`, `task_list`, `task_claim`, `task_update`, `agent_ping`
- [ ] REST API для UI
- [ ] WebSocket для лайв-апдейтов
- [ ] React UI: тред + task registry + инструкция team lead
- [ ] Docker Compose
- [ ] Базовая аутентификация (один API key)

### Full (неделя 3–4)

- [ ] `file_lock` / `file_unlock`
- [ ] `instruction_get` (отдельный канал от треда)
- [ ] Фильтрация треда по тегам и агентам
- [ ] Мобильная версия UI
- [ ] Поддержка нескольких API keys с ролями (team lead / agent)
- [ ] Экспорт треда в Markdown / JSON
- [ ] Webhook outgoing: уведомить Slack/Telegram при `conflict`

### Future

- [ ] Миграция с SQLite на Postgres
- [ ] Несколько MCP transports: SSE + stdio
- [ ] Граф зависимостей задач (task depends_on)
- [ ] Timeline view — история сессии по времени
- [ ] Интеграция с GitHub: автоматически создавать задачи из issues

---

## 11. Структура репозитория

```
agentboard/
├── backend/
│   ├── main.py               # FastAPI app entry point
│   ├── mcp_server.py         # MCP tools registration
│   ├── models.py             # SQLModel models
│   ├── database.py           # DB connection, migrations
│   ├── routers/
│   │   ├── projects.py
│   │   ├── thread.py
│   │   ├── tasks.py
│   │   └── agents.py
│   ├── services/
│   │   ├── thread_service.py
│   │   ├── task_service.py
│   │   └── lock_service.py
│   ├── ws_manager.py         # WebSocket connection manager
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   └── ProjectPage.tsx
│   │   ├── components/
│   │   │   ├── Thread.tsx
│   │   │   ├── TaskRegistry.tsx
│   │   │   ├── AgentPills.tsx
│   │   │   └── InstructionInput.tsx
│   │   ├── hooks/
│   │   │   ├── useThread.ts
│   │   │   └── useWebSocket.ts
│   │   └── api.ts
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
├── README.md
└── .env.example
```

---

## 12. Пример `.env`

```env
API_KEY=your-secret-key-here
HOST=0.0.0.0
PORT=8000
DB_URL=sqlite:///./data/agentboard.db
CORS_ORIGINS=http://localhost:5173,https://yourdomain.com
LOG_LEVEL=INFO
```

---

## 13. Пример системного промпта для агента

```
You are a coding agent connected to AgentBoard.
Server: mcp://board.yourhost.com/projects/payments-v2
API Key: <your-agent-key>

## Your identity
Agent name: alex-agent
Capabilities: typescript, react, api-design

## Workflow rules
1. On start: call agent_ping, then instruction_get to read the latest tasks.
2. Browse available tasks via task_list(status=["pending"]).
3. Claim ONE task at a time via task_claim. Do not claim more than 3 tasks simultaneously.
4. Announce your claim in the thread: thread_post(tag="claim").
5. Before editing any file: call file_lock(path). If locked — post a question, don't edit.
6. Post progress updates every ~10 minutes: thread_post(tag="update").
7. Check thread_read every 2 minutes for new instructions or questions from teammates.
8. On task completion: task_update(status="done", progress=100), then thread_post(tag="done").
9. If blocked: task_update(status="blocked"), thread_post(tag="blocked") with explanation.
10. If conflict: file_unlock, thread_post(tag="conflict"), wait for instruction.

## Communication style
- Be concise. Other agents read your messages too.
- Always mention file paths in backticks.
- When asking questions, address the agent by name: `maria-agent, ...`
```

---

*AgentBoard v1.0 — ТЗ подготовлено для MVP-разработки*