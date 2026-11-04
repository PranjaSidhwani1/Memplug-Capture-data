# Memplug

Memplug is a common memory layer for AI agents. The memory belongs to you. It is not locked inside ChatGPT, Claude, Cursor, Codex, or any other single product.

Today, each assistant keeps its own view of you. You repeat preferences, projects, and decisions every time you switch tools. Memplug sits beside those tools, stores the useful parts of what you already said, and hands that context back to an agent that is allowed to see it.

The product is in development. The public instance runs on free infrastructure and is not built to scale yet. The point of this stage is to find out whether the idea solves a real problem.

**Try it:** [https://memplug-capture-data.onrender.com/](https://memplug-capture-data.onrender.com/)

## The three things Memplug is building

### 1. Personal AI memory

A personal memory that follows you across AI agents and platforms. Preferences, past conversations, projects, and other facts you care about should be available in the next tool, so you do not explain the same things again.

What you can test now:

- Capture from **Cursor**, **Claude Code**, and **Codex**
- Automatic memories after a conversation grows, plus an explicit “remember this” through MCP
- The same account readable from those tools

ChatGPT and other chat products are part of this goal. They are not connected yet.

### 2. Shared team memory

A memory space for a team. Members and their agents can use common information, team knowledge, and earlier discussions, without mixing that store into anyone’s personal memory.

What you can test now:

- Create a team and share a join code
- Mint a key under that team
- Capture and retrieve only inside that team workspace

A personal key never reads a team store, and a team key never reads personal memory.

### 3. App-specific personal memory

Connect everyday apps such as Spotify, Zepto, and others so agents can understand preferences, activity, and day-to-day life, then personalise what they do.

This is not built. There are no app connectors in the current release. Feedback on whether this is worth building is useful.

## What is live today

The hosted console does three jobs:

1. **Capture.** A small hook file in the editor sends user and assistant messages to your account. The editor does not install a database or an embedding model.
2. **Memory.** Raw chat stays as conversation. Durable facts are written when a conversation passes about 1,000 tokens, or after it sits idle for 30 minutes. If you tell the agent to remember something, MCP can save that fact immediately.
3. **Retrieval.** The same API key opens an MCP server. The agent can load context for a new chat, search memories, and save a fact you asked it to keep.

Memories are grouped into domains such as Preferences, Coding, Work, Projects, Travel, and Shopping. You can read and delete them in the console.

### Current limits

- Development build on free instances. Expect slowness, and expect the site to be unavailable while an instance is waking up.
- Capture is limited to Cursor, Claude Code, and Codex, on macOS and Windows.
- App connectors (Spotify, Zepto, and the rest) are not implemented.
- ChatGPT is not a capture source yet.
- This is not a production memory service. Do not put secrets, passwords, or data you cannot afford to lose into it.

## Try the hosted product

Use this if you want to test Memplug, push on its limits, and send feedback. You do not need to clone the repo.

1. Open [https://memplug-capture-data.onrender.com/](https://memplug-capture-data.onrender.com/) and create an account. Sign-in and password reset use an email code.
2. Pick a workspace. Stay on **Personal**, or create a team and share the join code.
3. Mint an API key in that workspace. A key created under Personal is a personal key. A key created under a team is a team key. The secret is shown once, when the key is created.
4. Download the hook JSON for your editor and operating system. The file already contains that key.
5. Save the file where the editor looks, then restart the editor.

   | Editor | macOS | Windows |
   | --- | --- | --- |
   | Cursor | `~/.cursor/hooks.json` | `%USERPROFILE%\.cursor\hooks.json` |
   | Claude Code | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
   | Codex | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |

   Cursor: save it as the user hooks file, then restart Cursor.

   Claude Code: if `settings.json` already exists, merge the `hooks` object into it. Do not replace the rest of the file.

   Codex: open `/hooks`, trust the new command, and leave hooks running in the background.

6. Add the MCP server in Cursor (or another client that speaks remote MCP) with the same key:

   ```json
   {
     "mcpServers": {
       "memplug": {
         "url": "https://memplug-capture-data.onrender.com/mcp",
         "headers": {
           "Authorization": "Bearer <key for this workspace>"
         }
       }
     }
   }
   ```

   The console can copy this block with the key filled in after you create one.

After that, talk in the editor as you normally would. New messages land in the workspace that owns the key. On a new chat, the agent should call `get_user_context`. Later it can call `search_memory`. It should call `save_memory` only when you ask it to remember a specific fact.

### What to look for while testing

- Does a later chat actually use something you said earlier, on the same tool and on another tool?
- Does a team key stay inside the team, and a personal key stay personal?
- Are the saved memories true, useful, and specific, or are they noise?
- What fails: hooks, sign-in, extraction, search, or the console itself?

Bugs, missing features, and “this does not make sense” are all useful. Email [pranjaysidhwani@gmail.com](mailto:pranjaysidhwani@gmail.com) with the editor, macOS or Windows, whether the key was personal or a team key, and what you expected to happen.

## How a memory gets in and out

```text
Cursor / Claude Code / Codex
        |
        | hook  ->  POST /v1/capture/message
        v
   Raw conversation (MongoDB)
        |
        | checkpoint: ~1000 tokens, or 30 minutes idle
        v
   Extraction
        |
        v
   Durable memories (Postgres + vectors)
        |
        | MCP  /mcp
        v
   The agent, in that workspace only
```

You can also delete a memory from the console. The agent is not given a delete tool.

### MCP tools

Identity stays on the server. The model does not send a user id, a team id, or a permission scope. The API key chooses the workspace.

| Tool | When the agent uses it |
| --- | --- |
| `get_user_context` | Once, on the first message of a new chat. Pass that message as `task`. |
| `search_memory` | Later, when it needs a narrower lookup. |
| `save_memory` | When you ask it to remember a specific fact. |
| `list_domains` | To see domains that already have memories in this workspace. |
| `list_sub_domains` | To see groupings inside one domain. |

`get_user_context` and `search_memory` return memory text, not a record list. A domain is a top-level category. A sub-domain is an optional group inside one domain, such as Travel → Japan Trip.

Those five tools are the whole contract. The agent does not get a tool to edit or delete a memory.

## Run it locally

Local setup is for development. Testers should use the hosted console above.

Requirements:

- Python 3.10 or newer
- Node.js 22 (the UI is Vite + React)
- A MongoDB connection string
- For extraction and MCP search: a Postgres database with pgvector (`DATABASE_URL`) and Meta API settings (`META_API_KEY`, `META_MODEL`)
- For email codes: SMTP settings

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux, activate with `source .venv/bin/activate` and copy the example env with `cp .env.example .env`.

Fill in `.env`. Never commit it. Then start the API:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start the console:

```powershell
cd ui
npm install
npm run dev
```

- Console: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Local API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

The Vite server proxies `/v1` and `/health` to port 8000. Point MCP at `http://127.0.0.1:8000/mcp`. Set `MEMPLUG_PUBLIC_API_URL` to the URL the editor and MCP client can actually reach. Hook downloads embed that public URL.

API docs (`/docs`, `/redoc`, `/openapi.json`) are available when you run locally. They are turned off on the hosted Render service.

### Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `MONGODB_URI` | Yes | Conversation store |
| `MONGODB_DB` | No | Database name. Defaults to `memplug` |
| `DATABASE_URL` | For memory | Neon or other Postgres URL. pgvector holds embeddings |
| `META_API_KEY` | For extraction | Model key used to turn chat into memories |
| `META_MODEL` | For extraction | Model name for that call |
| `MEMPLUG_AUTH_SECRET` | On Render | Signs session tokens. Locally, a secret is generated into `.auth_secret` if this is empty |
| `MEMPLUG_PUBLIC_API_URL` | Recommended | Public base URL embedded in hook files and MCP config |
| `MEMPLUG_CAPTURE_API_KEY` | Legacy | Shared capture key. User and team keys from the console are what you should use |
| `MAIL_FROM` | For email codes | Visible sender, for example `Memplug <memplug@support.com>` |
| `SMTP_HOST` | For email codes | SMTP server |
| `SMTP_PORT` | No | Defaults to `587` |
| `SMTP_USERNAME` | For email codes | SMTP username |
| `SMTP_PASSWORD` | For email codes | SMTP password |
| `CHECKPOINT_TOKENS` | No | Token threshold before extraction. Defaults to `1000` |
| `CHECKPOINT_IDLE_MINUTES` | No | Idle window before extraction. Defaults to `30` |

Without `DATABASE_URL`, `META_API_KEY`, and `META_MODEL`, the API can still capture raw messages. It will not extract or search durable memories.

### Production build

`build.sh` installs Node if needed, builds `ui`, and installs Python dependencies. The API then serves the built console from `ui/dist`. Render runs that script, then:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Health check path: `/health`.

## Links

| | |
| --- | --- |
| Hosted console | [https://memplug-capture-data.onrender.com/](https://memplug-capture-data.onrender.com/) |
| MCP endpoint | [https://memplug-capture-data.onrender.com/mcp](https://memplug-capture-data.onrender.com/mcp) |
| Health | [https://memplug-capture-data.onrender.com/health](https://memplug-capture-data.onrender.com/health) |
| Feedback | [pranjaysidhwani@gmail.com](mailto:pranjaysidhwani@gmail.com) |

## Repository

```text
app/                FastAPI capture API, auth, teams, extraction
memory_mcp/         MCP server mounted at /mcp
ui/                 React console
build.sh            Render build: UI, then Python deps
render.yaml         Render service definition
requirements.txt    API dependencies
.env.example        Environment variable names, with empty values
```

## Feedback

The question this stage needs answered is whether a memory you own, shared across agents and optionally across a team, is something people will actually use.

Please try it, use it as much as you can, and say what broke, what you expected, and what you would not bother with. Feature ideas are welcome. So is “this does not solve a real problem.”

Write to [pranjaysidhwani@gmail.com](mailto:pranjaysidhwani@gmail.com).
