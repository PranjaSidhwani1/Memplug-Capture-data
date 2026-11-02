import { useEffect, useState } from "react";
import {
  configMeta,
  createKey,
  createTeam,
  downloadBundle,
  joinTeam,
  leaveTeam,
  listKeys,
  listTeams,
  login,
  me,
  revokeKey,
  signup,
  storedToken,
  storeToken,
} from "./api.js";

const TOOLS = [
  {
    id: "cursor",
    name: "Cursor",
    detail: "beforeSubmitPrompt and afterAgentResponse",
    note: "Save it as the user hooks file, then restart Cursor.",
  },
  {
    id: "claude",
    name: "Claude Code",
    detail: "UserPromptSubmit and Stop",
    note: "If settings.json already exists, merge this hooks object into it.",
  },
  {
    id: "codex",
    name: "Codex",
    detail: "UserPromptSubmit and Stop",
    note: "Open /hooks in Codex and trust the new command. Hooks run in the background.",
  },
];

function Mark() {
  return (
    <svg className="mark" viewBox="0 0 48 48" aria-hidden="true">
      <rect x="1.5" y="1.5" width="45" height="45" rx="4" />
      <path d="M16 20h10v8H16z" />
      <path d="M26 23h8M30 19v8" />
      <path d="M14 18v-4M18 18v-6M22 18v-4" />
    </svg>
  );
}

export default function App() {
  const [token, setToken] = useState(storedToken);
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(Boolean(storedToken()));

  useEffect(() => {
    if (!token) {
      setUser(null);
      setBooting(false);
      return;
    }
    let cancelled = false;
    me(token)
      .then((payload) => {
        if (!cancelled) setUser(payload.user);
      })
      .catch(() => {
        storeToken("");
        if (!cancelled) {
          setToken("");
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setBooting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  function signOut() {
    storeToken("");
    setToken("");
    setUser(null);
  }

  if (booting) {
    return (
      <div className="boot">
        <Mark />
        <p>Opening the console</p>
      </div>
    );
  }

  if (!user) {
    return (
      <ProductPage
        onSession={(nextToken, nextUser) => {
          storeToken(nextToken);
          setToken(nextToken);
          setUser(nextUser);
        }}
      />
    );
  }

  return <Console token={token} user={user} onSignOut={signOut} />;
}

function ProductPage({ onSession }) {
  const [auth, setAuth] = useState("");

  if (auth) {
    return (
      <AuthScreen
        mode={auth}
        onMode={setAuth}
        onBack={() => setAuth("")}
        onSession={onSession}
      />
    );
  }

  return (
    <div className="product">
      <header className="bar">
        <div className="brand">
          <Mark />
          <div>
            <strong>Memplug</strong>
            <span>Memory for agents</span>
          </div>
        </div>
        <div className="who">
          <button type="button" onClick={() => setAuth("login")}>
            Sign in
          </button>
          <button className="primary slim" type="button" onClick={() => setAuth("signup")}>
            Create account
          </button>
        </div>
      </header>
      <main>
        <section className="hero">
          <p className="eyebrow">A memory layer you own</p>
          <h1>Your agents remember the work. Your team can share it.</h1>
          <p className="lede">
            Memplug captures conversations from Cursor, Claude Code, and Codex, turns them into
            durable memories, and hands those memories back through MCP. A personal key stays
            yours. A team key belongs to that team only.
          </p>
          <div className="hero-actions">
            <button className="primary" type="button" onClick={() => setAuth("signup")}>
              Start with an account
            </button>
            <a href="#configure">How to configure</a>
          </div>
        </section>
        <section className="band" id="serve">
          <div className="section-head">
            <p className="eyebrow">What we serve</p>
            <h2>Capture, memory, and retrieval.</h2>
          </div>
          <div className="offer">
            <article>
              <span>01</span>
              <h3>Capture</h3>
              <p>
                A small hook file watches the editor. User and assistant messages are saved to
                your account. The editor does not install a database or an embedding model.
              </p>
            </article>
            <article>
              <span>02</span>
              <h3>Memory</h3>
              <p>
                When a conversation passes the token checkpoint, or sits for 30 minutes, Memplug
                writes the durable facts. Raw chat stays in the conversation. Memories are the
                record the agent can use later.
              </p>
            </article>
            <article>
              <span>03</span>
              <h3>Retrieval</h3>
              <p>
                The same API key opens an MCP server. The agent can load context for a task,
                search memories, and save a fact you asked it to remember.
              </p>
            </article>
          </div>
        </section>
        <section className="band split">
          <div>
            <p className="eyebrow">Why it is a product</p>
            <h2>The memory lives on Memplug, not on every laptop.</h2>
            <p className="lede tight">
              You download one JSON file. That file carries the key for one workspace. Personal
              and team memories are never mixed.
            </p>
          </div>
          <ul className="benefits">
            <li>The next session starts from what you already decided.</li>
            <li>A team key reads and writes only that team's memory.</li>
            <li>Cursor, Claude Code, and Codex use the same account.</li>
            <li>You choose the workspace before the key is minted.</li>
          </ul>
        </section>
        <section className="band" id="configure">
          <div className="section-head">
            <p className="eyebrow">Configure</p>
            <h2>Six steps, then the agent is connected.</h2>
          </div>
          <ol className="steps">
            <li>
              <span>01</span>
              <div>
                <h3>Create an account</h3>
                <p>The account is yours. Sign in when you need the console again.</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <h3>Pick a workspace</h3>
                <p>Stay on Personal, or create a team and share the join code. Someone else joins with that code.</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <h3>Mint the key there</h3>
                <p>A key created under Personal is a personal key. A key created under a team is a team key.</p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <h3>Download the hook JSON</h3>
                <p>Choose Cursor, Claude Code, or Codex, and macOS or Windows. The file already contains the key.</p>
              </div>
            </li>
            <li>
              <span>05</span>
              <div>
                <h3>Save it where the editor looks</h3>
                <p>The card shows the path. Restart the editor. New messages start landing in that workspace.</p>
              </div>
            </li>
            <li>
              <span>06</span>
              <div>
                <h3>Add the MCP server</h3>
                <p>Point Cursor at your Memplug URL with the same key. The agent then searches and saves in that workspace only.</p>
              </div>
            </li>
          </ol>
          <button className="primary" type="button" onClick={() => setAuth("signup")}>
            Create account
          </button>
        </section>
      </main>
    </div>
  );
}

function AuthScreen({ mode: initialMode, onMode, onBack, onSession }) {
  const [mode, setMode] = useState(initialMode || "login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const payload =
        mode === "signup"
          ? await signup(email, password, name)
          : await login(email, password);
      onSession(payload.token, payload.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="gate">
      <section className="plate">
        <button className="back" type="button" onClick={onBack}>
          Back to Memplug
        </button>
        <div className="plate-top">
          <Mark />
          <span>Memplug</span>
        </div>
        <p className="eyebrow">Capture console</p>
        <h1>
          Keys for the
          <br />
          agents you already use.
        </h1>
        <p className="lede">
          Sign in, mint an API key, and download the hook file for Cursor, Claude Code, or Codex.
          macOS and Windows each get their own command.
        </p>
        <ol className="specs">
          <li>
            <span>01</span>Cursor
          </li>
          <li>
            <span>02</span>Claude Code
          </li>
          <li>
            <span>03</span>Codex
          </li>
        </ol>
      </section>
      <section className="panel">
        <div className="mode">
          <button type="button" className={mode === "login" ? "on" : ""} onClick={() => { setMode("login"); onMode("login"); }}>
            Sign in
          </button>
          <button type="button" className={mode === "signup" ? "on" : ""} onClick={() => { setMode("signup"); onMode("signup"); }}>
            Create account
          </button>
        </div>
        <form onSubmit={submit}>
          {mode === "signup" && (
            <label>
              Name
              <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" maxLength={80} />
            </label>
          )}
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              minLength={mode === "signup" ? 8 : 1}
              required
            />
          </label>
          {mode === "signup" && <p className="hint">At least 8 characters. Stored as a hash.</p>}
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Working" : mode === "signup" ? "Create account" : "Enter"}
          </button>
        </form>
      </section>
    </main>
  );
}

function Console({ token, user, onSignOut }) {
  const [keys, setKeys] = useState([]);
  const [teams, setTeams] = useState([]);
  const [workspace, setWorkspace] = useState("");
  const [teamName, setTeamName] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [meta, setMeta] = useState(null);
  const [keyName, setKeyName] = useState("");
  const [selected, setSelected] = useState("");
  const [fresh, setFresh] = useState(null);
  const [system, setSystem] = useState("mac");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([listKeys(token), listTeams(token), configMeta(token)])
      .then(([keyPayload, teamPayload, metaPayload]) => {
        if (cancelled) return;
        setKeys(keyPayload.keys);
        setTeams(teamPayload.teams);
        setMeta(metaPayload);
        setSelected((current) => current || keyPayload.keys.find((item) => (item.workspace_type || "user") === "user")?.id || "");
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    const visible = keys.filter((item) => {
      const kind = item.workspace_type || "user";
      if (!workspace) return kind !== "team";
      return kind === "team" && item.workspace_id === workspace;
    });
    if (!visible.some((item) => item.id === selected)) {
      setSelected(visible[0]?.id || "");
    }
  }, [keys, workspace, selected]);

  async function mint(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const created = await createKey(token, keyName.trim() || "default", workspace);
      setFresh(created);
      setKeyName("");
      const next = await listKeys(token);
      setKeys(next.keys);
      setSelected(created.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id) {
    setError("");
    setNotice("");
    try {
      await revokeKey(token, id);
      const next = await listKeys(token);
      setKeys(next.keys);
      setSelected((current) => (current === id ? next.keys[0]?.id || "" : current));
      setFresh((current) => (current?.id === id ? null : current));
      setNotice("Key revoked. Downloads signed with it will stop working.");
    } catch (err) {
      setError(err.message);
    }
  }

  async function download(tool) {
    if (!selected) {
      setError("Create an API key first.");
      return;
    }
    setError("");
    setNotice("");
    setDownloading(tool);
    try {
      const filename = await downloadBundle(token, tool, system, selected);
      setNotice(`Saved ${filename}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloading("");
    }
  }

  async function copyKey() {
    if (!fresh?.key) return;
    try {
      await navigator.clipboard.writeText(fresh.key);
      setNotice("Key copied.");
    } catch {
      setError("Select the key and copy it manually.");
    }
  }

  async function refreshTeams(selectId) {
    const payload = await listTeams(token);
    setTeams(payload.teams);
    if (selectId) setWorkspace(selectId);
  }

  async function makeTeam(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const created = await createTeam(token, teamName.trim());
      setTeamName("");
      await refreshTeams(created.id);
      setNotice(`Team ${created.name} is ready. Share the join code.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function enterTeam(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const joined = await joinTeam(token, joinCode.trim());
      setJoinCode("");
      await refreshTeams(joined.id);
      setNotice(joined.role === "owner" ? `You already own ${joined.name}.` : `You joined ${joined.name}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function exitTeam() {
    if (!activeTeam) return;
    setError("");
    setNotice("");
    try {
      await leaveTeam(token, activeTeam.id);
      setWorkspace("");
      await refreshTeams("");
      setNotice(`You left ${activeTeam.name}.`);
    } catch (err) {
      setError(err.message);
    }
  }

  const osLabel = system === "mac" ? "macOS" : "Windows";
  const activeTeam = teams.find((item) => item.id === workspace) || null;
  const visibleKeys = keys.filter((item) => {
    const kind = item.workspace_type || "user";
    if (!workspace) return kind !== "team";
    return kind === "team" && item.workspace_id === workspace;
  });
  const workspaceLabel = activeTeam ? activeTeam.name : "Personal";

  return (
    <div className="console">
      <header className="bar">
        <div className="brand">
          <Mark />
          <div>
            <strong>Memplug</strong>
            <span>Capture</span>
          </div>
        </div>
        <div className="who">
          <span>{user.name || user.email}</span>
          <button type="button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      <div className="workspace">
        <section className="keys">
          <div className="section-head">
            <p className="eyebrow">Workspace</p>
            <h2>Personal or team</h2>
          </div>
          <div className="spaces" role="group" aria-label="Workspace">
            <button type="button" className={workspace === "" ? "on" : ""} onClick={() => setWorkspace("")}>
              Personal
            </button>
            {teams.map((item) => (
              <button
                type="button"
                key={item.id}
                className={workspace === item.id ? "on" : ""}
                onClick={() => setWorkspace(item.id)}
              >
                {item.name}
              </button>
            ))}
          </div>
          <form className="mint" onSubmit={makeTeam}>
            <label>
              New team
              <input
                value={teamName}
                onChange={(event) => setTeamName(event.target.value)}
                placeholder="Studio"
                maxLength={80}
              />
            </label>
            <button className="primary" type="submit" disabled={busy || !teamName.trim()}>
              Create
            </button>
          </form>
          <form className="mint" onSubmit={enterTeam}>
            <label>
              Join code
              <input
                value={joinCode}
                onChange={(event) => setJoinCode(event.target.value)}
                placeholder="A1B2C3D4"
                maxLength={32}
              />
            </label>
            <button className="primary" type="submit" disabled={busy || !joinCode.trim()}>
              Join
            </button>
          </form>
          {activeTeam && (
            <div className="team-note">
              <p>
                {activeTeam.role === "owner"
                  ? `You own ${activeTeam.name}. Share this code so someone can join.`
                  : `You are a member of ${activeTeam.name}.`}
              </p>
              {activeTeam.role === "owner" && <code>{activeTeam.join_code}</code>}
              {activeTeam.role !== "owner" && (
                <button type="button" className="danger" onClick={exitTeam}>
                  Leave team
                </button>
              )}
            </div>
          )}
          <div className="section-head">
            <p className="eyebrow">Account</p>
            <h2>API keys</h2>
          </div>
          <p className="lede tight">
            A key is minted for {workspaceLabel}. The hook JSON carries that key, and the server treats every call as{" "}
            {activeTeam ? "that team" : "your personal memory"}.
          </p>
          <form className="mint" onSubmit={mint}>
            <label>
              Label
              <input
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
                placeholder="laptop"
                maxLength={40}
              />
            </label>
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "Minting" : "Create key"}
            </button>
          </form>
          {fresh && (
            <div className="reveal">
              <div>
                <p className="eyebrow">New key</p>
                <code>{fresh.key}</code>
              </div>
              <button type="button" onClick={copyKey}>
                Copy
              </button>
            </div>
          )}
          <ul className="key-list">
            {visibleKeys.length === 0 && <li className="empty">No keys for {workspaceLabel} yet.</li>}
            {visibleKeys.map((item) => (
              <li key={item.id}>
                <label>
                  <input
                    type="radio"
                    name="signing-key"
                    checked={selected === item.id}
                    onChange={() => setSelected(item.id)}
                  />
                  <span>
                    <strong>{item.name}</strong>
                    <code>{item.prefix}…</code>
                  </span>
                </label>
                <button type="button" className="danger" onClick={() => revoke(item.id)}>
                  Revoke
                </button>
              </li>
            ))}
          </ul>
          {error && <p className="error">{error}</p>}
          {notice && <p className="notice">{notice}</p>}
        </section>
        <section className="drops">
          <div className="section-head row">
            <div>
              <p className="eyebrow">Install</p>
              <h2>Hook files</h2>
            </div>
            <div className="os" role="group" aria-label="Operating system">
              <button type="button" className={system === "mac" ? "on" : ""} onClick={() => setSystem("mac")}>
                macOS
              </button>
              <button
                type="button"
                className={system === "windows" ? "on" : ""}
                onClick={() => setSystem("windows")}
              >
                Windows
              </button>
            </div>
          </div>
          <p className="lede tight">
            Save this file at the path on the card. It is the whole hook: the command inside it reads the editor
            event and posts it. Python 3 has to be on PATH. Nothing else is installed.
          </p>
          {meta?.api_url && (
            <p className="endpoint">
              Calls <code>{meta.api_url}</code>
            </p>
          )}
          <div className="cards">
            {TOOLS.map((tool) => {
              const place = meta?.destinations?.[`${tool.id}:${system}`] || "";
              return (
                <article key={tool.id} className="card">
                  <header>
                    <h3>{tool.name}</h3>
                    <span>{osLabel}</span>
                  </header>
                  <p>{tool.detail}</p>
                  <code className="path">{place}</code>
                  <p className="hint">{tool.note}</p>
                  <button type="button" disabled={!selected || downloading === tool.id} onClick={() => download(tool.id)}>
                    {downloading === tool.id ? "Preparing" : `Download ${osLabel} JSON`}
                  </button>
                </article>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
