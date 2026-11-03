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
  requestReset,
  resetPassword,
  revokeKey,
  signup,
  storedToken,
  storeToken,
  verifyOtp,
} from "./api.js";

const SUPPORT_EMAIL = "pranjaysidhwani@gmail.com";

function contactHref(topic) {
  const subject = encodeURIComponent(topic);
  return `mailto:${SUPPORT_EMAIL}?subject=${subject}`;
}

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
          <a href={contactHref("Memplug")}>Contact</a>
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
        <section className="band split" id="contact">
          <div>
            <p className="eyebrow">Contact</p>
            <h2>When a hook, a key, or a team will not work.</h2>
            <p className="lede tight">
              Write with the editor, the workspace, and what you expected to happen. Personal and
              team keys are separate, so say which one you used.
            </p>
          </div>
          <p className="contact-mail">
            <a href={contactHref("Memplug issue")}>{SUPPORT_EMAIL}</a>
          </p>
        </section>
      </main>
    </div>
  );
}

function AuthScreen({ mode: initialMode, onMode, onBack, onSession }) {
  const [mode, setMode] = useState(initialMode || "login");
  const [step, setStep] = useState("credentials");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function switchMode(next) {
    setMode(next);
    onMode(next);
    setStep("credentials");
    setCode("");
    setError("");
    setNotice("");
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (step === "otp") {
        const payload = await verifyOtp(email, code);
        onSession(payload.token, payload.user);
        return;
      }
      if (step === "forgot") {
        await requestReset(email);
        setStep("reset");
        setCode("");
        setPassword("");
        setNotice("If that account exists, we sent a reset code.");
        return;
      }
      if (step === "reset") {
        const payload = await resetPassword(email, code, password);
        onSession(payload.token, payload.user);
        return;
      }
      if (mode === "signup") {
        const payload = await signup(email, password, name);
        onSession(payload.token, payload.user);
        return;
      }
      const payload = await login(email, password);
      if (payload.otp_required) {
        setStep("otp");
        setCode("");
        setNotice(`We sent a 6-digit code to ${email}.`);
        return;
      }
      onSession(payload.token, payload.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const showPassword = step === "credentials" || step === "reset";
  const showEmail = step !== "otp";

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
          <button type="button" className={mode === "login" ? "on" : ""} onClick={() => switchMode("login")}>
            Sign in
          </button>
          <button type="button" className={mode === "signup" ? "on" : ""} onClick={() => switchMode("signup")}>
            Create account
          </button>
        </div>
        <form onSubmit={submit}>
          {mode === "signup" && step === "credentials" && (
            <label>
              Name
              <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" maxLength={80} />
            </label>
          )}
          {showEmail && (
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
                readOnly={step === "reset"}
              />
            </label>
          )}
          {(step === "otp" || step === "reset") && (
            <label>
              Code
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                required
              />
            </label>
          )}
          {showPassword && (
            <label>
              {step === "reset" ? "New password" : "Password"}
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={mode === "signup" || step === "reset" ? "new-password" : "current-password"}
                minLength={mode === "signup" || step === "reset" ? 8 : 1}
                required
              />
            </label>
          )}
          {mode === "signup" && step === "credentials" && <p className="hint">At least 8 characters. Stored as a hash.</p>}
          {step === "otp" && <p className="hint">The code expires in 10 minutes.</p>}
          {notice && <p className="notice">{notice}</p>}
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>
            {busy
              ? "Working"
              : step === "otp"
                ? "Confirm code"
                : step === "forgot"
                  ? "Send reset code"
                  : step === "reset"
                    ? "Save password"
                    : mode === "signup"
                      ? "Create account"
                      : "Enter"}
          </button>
          {mode === "login" && step === "credentials" && (
            <button
              className="text-button"
              type="button"
              onClick={() => {
                setStep("forgot");
                setError("");
                setNotice("");
              }}
            >
              Forgot password?
            </button>
          )}
          {mode === "login" && step !== "credentials" && (
            <button
              className="text-button"
              type="button"
              onClick={() => {
                setStep("credentials");
                setCode("");
                setError("");
                setNotice("");
              }}
            >
              Back to sign in
            </button>
          )}
        </form>
      </section>
    </main>
  );
}

function belongsToWorkspace(item, workspace) {
  const kind = item.workspace_type || "user";
  if (!workspace) return kind !== "team";
  return kind === "team" && item.workspace_id === workspace;
}

function mcpConfig(url, key) {
  return JSON.stringify(
    {
      mcpServers: {
        memplug: {
          url: url || "https://your-memplug-host/mcp",
          headers: { Authorization: `Bearer ${key || "<key for this workspace>"}` },
        },
      },
    },
    null,
    2,
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
  const [teamError, setTeamError] = useState("");
  const [notice, setNotice] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const [teamBusy, setTeamBusy] = useState(false);
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
    const visible = keys.filter((item) => belongsToWorkspace(item, workspace));
    if (!visible.some((item) => item.id === selected)) {
      setSelected(visible[0]?.id || "");
    }
    setFresh((current) => (current && belongsToWorkspace(current, workspace) ? current : null));
  }, [keys, workspace, selected]);

  async function mint(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setKeyBusy(true);
    try {
      const created = await createKey(token, keyName.trim() || "default", workspace);
      setFresh(created);
      setKeyName("");
      const next = await listKeys(token);
      setKeys(next.keys);
      setSelected(created.id);
      setNotice(
        created.workspace_type === "team"
          ? "Team key created. It reads and writes this team only. Copy it now."
          : "Personal key created. It reads and writes your memories only. Copy it now.",
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setKeyBusy(false);
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

  async function refreshTeams(selectId) {
    const payload = await listTeams(token);
    setTeams(payload.teams);
    if (selectId) setWorkspace(selectId);
  }

  async function makeTeam(event) {
    event.preventDefault();
    setTeamError("");
    setNotice("");
    setTeamBusy(true);
    try {
      const created = await createTeam(token, teamName.trim());
      setTeamName("");
      await refreshTeams(created.id);
      setNotice(`${created.name} is ready. Share the join code on that team card. A key for it is a separate step.`);
    } catch (err) {
      setTeamError(err.message);
    } finally {
      setTeamBusy(false);
    }
  }

  async function enterTeam(event) {
    event.preventDefault();
    setTeamError("");
    setNotice("");
    setTeamBusy(true);
    try {
      const joined = await joinTeam(token, joinCode.trim());
      setJoinCode("");
      await refreshTeams(joined.id);
      setNotice(
        joined.role === "owner"
          ? `You already own ${joined.name}.`
          : `You joined ${joined.name}. Create a key for it before you download a hook.`,
      );
    } catch (err) {
      setTeamError(err.message);
    } finally {
      setTeamBusy(false);
    }
  }

  async function exitTeam(team) {
    setTeamError("");
    setNotice("");
    try {
      await leaveTeam(token, team.id);
      if (workspace === team.id) setWorkspace("");
      await refreshTeams("");
      setNotice(`You left ${team.name}. Keys you made for it no longer open that memory.`);
    } catch (err) {
      setTeamError(err.message);
    }
  }

  async function copyText(value, ok) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(ok);
      setError("");
      setTeamError("");
    } catch {
      setError("Select the text and copy it manually.");
    }
  }

  const osLabel = system === "mac" ? "macOS" : "Windows";
  const activeTeam = teams.find((item) => item.id === workspace) || null;
  const visibleKeys = keys.filter((item) => belongsToWorkspace(item, workspace));
  const workspaceLabel = activeTeam ? activeTeam.name : "Personal";
  const keyKind = activeTeam ? "team" : "personal";
  const mcpUrl = meta?.api_url ? `${meta.api_url.replace(/\/$/, "")}/mcp` : "";
  const snippet = mcpConfig(mcpUrl, fresh?.key || "");

  return (
    <div className="console">
      <header className="bar">
        <div className="brand">
          <Mark />
          <div>
            <strong>Memplug</strong>
            <span>Console</span>
          </div>
        </div>
        <div className="who">
          <a href="#process">Setup</a>
          <a href={contactHref("Memplug issue")}>Contact</a>
          <span>{user.name || user.email}</span>
          <button type="button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      {(error || notice) && <p className={error ? "error status" : "notice status"}>{error || notice}</p>}
      <main className="desk">
        <section className="band" id="process">
          <div className="section-head">
            <p className="eyebrow">After you sign in</p>
            <h2>Connect this account to an editor.</h2>
          </div>
          <ol className="steps">
            <li>
              <span>01</span>
              <div>
                <h3>Open one workspace</h3>
                <p>
                  Personal is your own memory. Create a team when several people should share one memory, then
                  send the join code. Joining does not create a key.
                </p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <h3>Create the key inside that workspace</h3>
                <p>
                  The open card decides the key. A personal key never reads a team. A team key never reads your
                  personal memory, and it never reads another team. You need one key per workspace you use.
                </p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <h3>Download the hook for the selected key</h3>
                <p>
                  Choose the editor and macOS or Windows. The JSON already contains the selected key. Save it at
                  the path on the card and restart the editor. Python 3 has to be on PATH. Nothing else is installed
                  on the machine.
                </p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <h3>Add MCP with that same key</h3>
                <p>
                  The agent does not send a user id. The key is the workspace. Paste the config below into Cursor.
                  Memories are written when a conversation crosses the token checkpoint, or after 30 minutes of
                  quiet. The raw chat stays. The memory is what the agent can search later.
                </p>
              </div>
            </li>
          </ol>
        </section>

        <section className="band" id="workspaces">
          <div className="section-head">
            <p className="eyebrow">Workspaces</p>
            <h2>Choose where the next key belongs.</h2>
          </div>
          <p className="lede tight">
            Open a card first. Create and join only change membership. They do not mint a key.
          </p>
          <div className="space-grid">
            <article className={workspace === "" ? "space on" : "space"}>
              <button type="button" className="space-pick" onClick={() => setWorkspace("")}>
                <span>Account</span>
                <strong>Personal</strong>
                <p>Your memories only. Open this before you create a personal key.</p>
              </button>
            </article>
            {teams.map((item) => (
              <article key={item.id} className={workspace === item.id ? "space on" : "space"}>
                <button type="button" className="space-pick" onClick={() => setWorkspace(item.id)}>
                  <span>{item.role === "owner" ? "Owner" : "Member"}</span>
                  <strong>{item.name}</strong>
                  <p>Team memory only. A key made while this card is open belongs to {item.name}.</p>
                </button>
                {item.role === "owner" ? (
                  <div className="code-row">
                    <code>{item.join_code}</code>
                    <button type="button" onClick={() => copyText(item.join_code, "Join code copied.")}>
                      Copy code
                    </button>
                  </div>
                ) : (
                  <button type="button" className="danger text" onClick={() => exitTeam(item)}>
                    Leave team
                  </button>
                )}
              </article>
            ))}
          </div>
          <div className="team-actions">
            <form onSubmit={makeTeam}>
              <h3>Create a team</h3>
              <p>You become the owner. The card shows a join code you can send.</p>
              <label>
                Team name
                <input
                  value={teamName}
                  onChange={(event) => setTeamName(event.target.value)}
                  placeholder="Studio"
                  maxLength={80}
                />
              </label>
              <button className="primary" type="submit" disabled={teamBusy || !teamName.trim()}>
                {teamBusy ? "Creating" : "Create team"}
              </button>
            </form>
            <form onSubmit={enterTeam}>
              <h3>Join a team</h3>
              <p>Use the code the owner sent. You can then create a key for that team.</p>
              <label>
                Join code
                <input
                  value={joinCode}
                  onChange={(event) => setJoinCode(event.target.value)}
                  placeholder="A1B2C3D4"
                  maxLength={32}
                  autoCapitalize="characters"
                />
              </label>
              <button className="primary" type="submit" disabled={teamBusy || !joinCode.trim()}>
                {teamBusy ? "Joining" : "Join team"}
              </button>
            </form>
          </div>
          {teamError && <p className="error">{teamError}</p>}
        </section>

        <section className="band" id="keys">
          <div className="section-head">
            <p className="eyebrow">{keyKind === "team" ? "Team key" : "Personal key"}</p>
            <h2>{keyKind === "team" ? `Key for ${workspaceLabel}` : "Key for your account"}</h2>
          </div>
          <p className="lede tight">
            {activeTeam
              ? `This creates a team key. Capture and MCP calls with it read and write ${activeTeam.name} only.`
              : "This creates a personal key. Capture and MCP calls with it read and write your memories only."}
          </p>
          <form className="key-form" onSubmit={mint}>
            <label>
              Label
              <input
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
                placeholder={activeTeam ? "studio-laptop" : "laptop"}
                maxLength={40}
              />
            </label>
            <button className="primary" type="submit" disabled={keyBusy}>
              {keyBusy ? "Creating" : keyKind === "team" ? "Create team key" : "Create personal key"}
            </button>
          </form>
          {fresh && belongsToWorkspace(fresh, workspace) && (
            <div className="reveal">
              <div>
                <p className="eyebrow">{fresh.workspace_type === "team" ? "Team key" : "Personal key"}</p>
                <code>{fresh.key}</code>
              </div>
              <button type="button" onClick={() => copyText(fresh.key, "Key copied.")}>
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
                    <code>
                      {item.workspace_type === "team" ? "Team" : "Personal"} · {item.prefix}…
                    </code>
                  </span>
                </label>
                <button type="button" className="danger" onClick={() => revoke(item.id)}>
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="band" id="install">
          <div className="section-head row">
            <div>
              <p className="eyebrow">Install</p>
              <h2>Hook file for {workspaceLabel}</h2>
            </div>
            <div className="os" role="group" aria-label="Operating system">
              <button type="button" className={system === "mac" ? "on" : ""} onClick={() => setSystem("mac")}>
                macOS
              </button>
              <button type="button" className={system === "windows" ? "on" : ""} onClick={() => setSystem("windows")}>
                Windows
              </button>
            </div>
          </div>
          <p className="lede tight">
            {selected
              ? `The download uses the selected ${keyKind} key. Save the file at the path, then restart the editor.`
              : `Create a ${keyKind} key above, then download it. Save the file at the path and restart the editor.`}
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
          <div className="mcp">
            <div className="section-head row">
              <div>
                <h3>MCP for {workspaceLabel}</h3>
                <p className="lede tight">
                  Same host, path <code>/mcp</code>, same {keyKind} key. The secret is filled in after you create a
                  key on this page. Older keys stay hidden, so create a new one when you need the value again.
                </p>
              </div>
              <button type="button" onClick={() => copyText(snippet, "MCP config copied.")}>
                Copy config
              </button>
            </div>
            <pre>{snippet}</pre>
          </div>
        </section>

        <section className="band split" id="contact">
          <div>
            <p className="eyebrow">Contact</p>
            <h2>When a step fails.</h2>
            <p className="lede tight">
              Include the editor, macOS or Windows, whether the key was personal or a team, and the message you saw.
            </p>
          </div>
          <p className="contact-mail">
            <a href={contactHref("Memplug issue")}>{SUPPORT_EMAIL}</a>
          </p>
        </section>
      </main>
    </div>
  );
}
