import { useEffect, useState } from "react";
import {
  configMeta,
  createKey,
  downloadBundle,
  listKeys,
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
      <AuthScreen
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

function AuthScreen({ onSession }) {
  const [mode, setMode] = useState("login");
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
          <button type="button" className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>
            Sign in
          </button>
          <button type="button" className={mode === "signup" ? "on" : ""} onClick={() => setMode("signup")}>
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
    Promise.all([listKeys(token), configMeta(token)])
      .then(([keyPayload, metaPayload]) => {
        if (cancelled) return;
        setKeys(keyPayload.keys);
        setMeta(metaPayload);
        setSelected((current) => current || keyPayload.keys[0]?.id || "");
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function mint(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const created = await createKey(token, keyName.trim() || "default");
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

  const osLabel = system === "mac" ? "macOS" : "Windows";

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
            <p className="eyebrow">Account</p>
            <h2>API keys</h2>
          </div>
          <p className="lede tight">
            A key identifies you. The hook sends it as a bearer token. Messages land on your user, not a shared bucket.
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
            {keys.length === 0 && <li className="empty">No active keys yet.</li>}
            {keys.map((item) => (
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
            Install capture on that machine so Python can import <code>memplug_capture</code>, then save the file at the
            path on the card. The chosen key is written into the command.
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
