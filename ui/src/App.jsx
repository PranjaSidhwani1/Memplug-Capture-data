import { useEffect, useState } from "react";
import {
  configMeta,
  createKey,
  createTeam,
  downloadBundle,
  joinTeam,
  leaveTeam,
  listData,
  listKeys,
  listTeams,
  login,
  me,
  openPortal,
  removeMemory,
  requestReset,
  resetPassword,
  resumePlan,
  revokeKey,
  signup,
  startCheckout,
  storedToken,
  storeToken,
  submitSupport,
  syncBilling,
  billingPlans,
  billingAccount,
  cancelPlan,
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
    detail: "beforeSubmitPrompt, afterAgentResponse, and postToolUse",
    note: "Save it as the user hooks file, then restart Cursor.",
  },
  {
    id: "claude",
    name: "Claude Code",
    detail: "UserPromptSubmit, Stop, and PostToolUse",
    note: "If settings.json already exists, merge this hooks object into it.",
  },
  {
    id: "codex",
    name: "Codex",
    detail: "UserPromptSubmit, Stop, and PostToolUse",
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
  const [page, setPage] = useState("overview");

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
        <nav className="tabs" aria-label="Site">
          <button type="button" className={page === "overview" ? "on" : ""} onClick={() => setPage("overview")}>
            Overview
          </button>
          <button type="button" className={page === "pricing" ? "on" : ""} onClick={() => setPage("pricing")}>
            Pricing
          </button>
          <button type="button" className={page === "docs" ? "on" : ""} onClick={() => setPage("docs")}>
            Docs
          </button>
        </nav>
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
        {page === "pricing" ? (
          <Pricing onStart={() => setAuth("signup")} />
        ) : page === "docs" ? (
          <section className="band open" id="configure">
            <div className="section-head">
              <p className="eyebrow">Docs</p>
              <h2>How to configure</h2>
            </div>
            <p className="lede tight">
              Six steps from a new account to an editor that can capture chat and search memory.
            </p>
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
        ) : (
          <>
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
            <button className="quiet" type="button" onClick={() => setPage("docs")}>
              How to configure
            </button>
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
                A small hook file watches the editor. User prompts, assistant replies, and tool
                calls are saved to your account. The editor does not install a database or an
                embedding model.
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
          </>
        )}
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

function stamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString();
}

function inScope(item, scope) {
  if (scope === "all") return true;
  if (scope === "personal") return item.owner_type !== "team";
  return item.owner_type === "team" && item.owner_id === scope;
}

function DataView({ token, teams }) {
  const [records, setRecords] = useState(null);
  const [scope, setScope] = useState("all");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [removing, setRemoving] = useState("");

  useEffect(() => {
    let cancelled = false;
    listData(token)
      .then((payload) => {
        if (!cancelled) setRecords(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (scope !== "all" && scope !== "personal" && !teams.some((team) => team.id === scope)) {
      setScope("all");
    }
  }, [teams, scope]);

  async function remove(item) {
    if (!window.confirm("Remove this memory? It is deleted for this workspace.")) return;
    setRemoving(item.id);
    setError("");
    setNotice("");
    try {
      await removeMemory(token, item.id);
      setRecords((current) => {
        if (!current) return current;
        return { ...current, memories: current.memories.filter((row) => row.id !== item.id) };
      });
      setNotice("Memory removed.");
    } catch (err) {
      setError(err.message);
    } finally {
      setRemoving("");
    }
  }

  const memories = (records?.memories || []).filter((item) => inScope(item, scope));
  const owners = [];
  if (scope === "all" || scope === "personal") owners.push({ id: "personal", name: "Personal" });
  for (const team of teams) {
    if (scope === "all" || scope === team.id) owners.push({ id: team.id, name: team.name });
  }

  return (
    <section className="band open" id="data">
      <div className="section-head">
        <p className="eyebrow">Data</p>
        <h2>What this account holds.</h2>
      </div>
      <p className="lede tight">
        Personal memories are only yours. Every team you have joined is included, and any memory can be removed.
      </p>
      <div className="scope" role="group" aria-label="Workspace">
        <button type="button" className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>
          All
        </button>
        <button type="button" className={scope === "personal" ? "on" : ""} onClick={() => setScope("personal")}>
          Personal
        </button>
        {teams.map((team) => (
          <button
            key={team.id}
            type="button"
            className={scope === team.id ? "on" : ""}
            onClick={() => setScope(team.id)}
          >
            {team.name}
          </button>
        ))}
      </div>
      {(error || notice) && <p className={error ? "error" : "notice"}>{error || notice}</p>}
      {records === null && !error && <p className="hint">Loading data</p>}
      {records && memories.length === 0 && <p className="hint">No memories for this view yet.</p>}
      {owners.map((owner) => {
        const ownedMemories = memories.filter((item) =>
          owner.id === "personal" ? item.owner_type !== "team" : item.owner_id === owner.id,
        );
        if (ownedMemories.length === 0) return null;
        return (
          <section key={owner.id} className="data-owner">
            <h3>{owner.name}</h3>
            <div className="records">
              {ownedMemories.map((item) => (
                <article key={item.id} className="record">
                  <div>
                    <p className="meta">
                      {[item.domain, item.sub_domain, item.memory_type, item.source, stamp(item.updated_at)]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    <p>{item.content}</p>
                  </div>
                  <button
                    type="button"
                    className="danger text"
                    disabled={removing === item.id}
                    onClick={() => remove(item)}
                  >
                    {removing === item.id ? "Removing" : "Remove"}
                  </button>
                </article>
              ))}
            </div>
          </section>
        );
      })}
    </section>
  );
}

const FALLBACK_PRODUCTS = [
  {
    id: "personal",
    name: "Personal AI memory",
    summary: "Capture from Cursor, Claude Code, and Codex. Your agents recall it through MCP.",
    available: true,
  },
  {
    id: "team",
    name: "Shared team memory",
    summary: "Team workspaces, join codes, and team keys that never read personal memory.",
    available: true,
  },
  {
    id: "apps",
    name: "App memory",
    summary: "Connectors for everyday apps such as Spotify and Zepto.",
    available: false,
  },
];

const FALLBACK_PLANS = [
  {
    id: "free",
    name: "Free",
    price_label: "$0",
    period: "forever",
    points: [
      "Personal AI memory",
      "App memory when it ships",
      "Memories kept for 15 days",
      "100 memory fetches a day",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    price_label: "$19",
    period: "per month",
    points: [
      "Personal AI memory",
      "App memory when it ships",
      "Memories kept for 6 months",
      "Unlimited memory fetches",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price_label: "$99",
    period: "per month",
    points: [
      "Shared team memory: 5 teams, 25 members each",
      "Everything in Pro for your own account",
      "Memories kept until you delete them",
      "Unlimited memory fetches",
      "Priority support requests from the console",
    ],
  },
];

function formatWhen(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function Pricing({ onStart }) {
  const [plans, setPlans] = useState(FALLBACK_PLANS);
  const [products, setProducts] = useState(FALLBACK_PRODUCTS);

  useEffect(() => {
    let cancelled = false;
    billingPlans()
      .then((payload) => {
        if (cancelled) return;
        if (payload.plans?.length) setPlans(payload.plans);
        if (payload.products?.length) setProducts(payload.products);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="band open">
      <div className="section-head">
        <p className="eyebrow">Pricing</p>
        <h2>Three plans</h2>
      </div>
      <p className="lede tight">
        Free and Pro cover personal AI memory and app memory. Shared team memory is Enterprise only. Card checkout opens after you sign in.
      </p>
      <div className="product-strip">
        {products.map((product) => (
          <article key={product.id}>
            <h3>
              {product.name}
              {!product.available ? <span>Coming soon</span> : null}
            </h3>
            <p>{product.summary}</p>
          </article>
        ))}
      </div>
      <div className="plan-grid">
        {plans.map((plan) => (
          <article className="card" key={plan.id}>
            <header>
              <h3>{plan.name}</h3>
              <span>{plan.period}</span>
            </header>
            <p className="amount">{plan.price_label}</p>
            <ul>
              {plan.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
            <button className="primary" type="button" onClick={onStart}>
              {plan.id === "free" ? "Create a free account" : `Get ${plan.name}`}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function PlanView({ token }) {
  const [account, setAccount] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const payload = await billingAccount(token);
    setAccount(payload);
    return payload;
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const flag = params.get("billing");
    const sessionId = params.get("session_id") || "";
    if (flag || sessionId) {
      const url = new URL(window.location.href);
      url.searchParams.delete("billing");
      url.searchParams.delete("session_id");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
    if (flag === "cancel") {
      setNotice("Checkout was canceled. The current plan is unchanged.");
      load().catch((err) => setError(err.message));
      return;
    }
    if (flag === "return") {
      setNotice("Back from the billing portal.");
    }
    const start = flag === "success" || Boolean(sessionId) ? syncBilling(token, sessionId) : load();
    start
      .then((payload) => {
        setAccount(payload);
        if (flag === "success") {
          setNotice(
            payload.plan === "free"
              ? "Payment is confirmed with Stripe. Refreshing the plan again if it is still catching up."
              : `You are on ${payload.plan_name}.`,
          );
        }
      })
      .catch((err) => setError(err.message));
  }, [token]);

  useEffect(() => {
    if (!account || account.plan !== "free") return undefined;
    const paramsHadSuccess = notice.includes("catching up");
    if (!paramsHadSuccess) return undefined;
    const timer = window.setInterval(() => {
      syncBilling(token)
        .then((payload) => {
          setAccount(payload);
          if (payload.plan !== "free") {
            setNotice(`You are on ${payload.plan_name}.`);
            window.clearInterval(timer);
          }
        })
        .catch(() => {});
    }, 2500);
    return () => window.clearInterval(timer);
  }, [account, notice, token]);

  async function choose(plan) {
    setError("");
    setNotice("");
    setBusy(plan.id);
    try {
      if (plan.id === "free") {
        const ok = window.confirm(
          "Stop renewing at the end of this billing period? You keep the paid plan until then. After that, Free retention applies and older memories are removed.",
        );
        if (!ok) return;
        const payload = await cancelPlan(token);
        setAccount(payload);
        setNotice(
          payload.subscription?.cancel_at
            ? `Renewal stops on ${formatWhen(payload.subscription.cancel_at)}. You stay on ${payload.plan_name} until then.`
            : "Renewal is set to stop at the end of the paid period.",
        );
        return;
      }
      const payload = await startCheckout(token, plan.id);
      if (payload.url) {
        window.location.assign(payload.url);
        return;
      }
      const refreshed = await load();
      if (payload.status === "changed") setNotice(`Switched to ${refreshed.plan_name}.`);
      else if (payload.status === "resumed") setNotice("Renewal is on again.");
      else if (payload.status === "action_required") {
        setNotice("Stripe needs another card confirmation for that upgrade.");
      } else {
        setNotice(`You are on ${refreshed.plan_name}.`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function resume() {
    setError("");
    setBusy("resume");
    try {
      const payload = await resumePlan(token);
      setAccount(payload);
      setNotice("Renewal is on again.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function manage() {
    setError("");
    setBusy("portal");
    try {
      const payload = await openPortal(token);
      window.location.assign(payload.url);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function sendSupport(event) {
    event.preventDefault();
    setError("");
    setBusy("support");
    try {
      const payload = await submitSupport(token, subject, message);
      setSubject("");
      setMessage("");
      setNotice(
        payload.priority
          ? "Priority support request sent."
          : payload.emailed
            ? "Support request sent."
            : "Support request saved. Mail is not configured on the server yet.",
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const usage = account
    ? account.fetch_limit == null
      ? `${account.fetches_today} memory fetches today. No daily cap.`
      : `${account.fetches_today} of ${account.fetch_limit} memory fetches used today.`
    : "";
  const subscription = account?.subscription;
  const cancelAt = subscription?.cancel_at;

  return (
    <section className="band open">
      <div className="section-head">
        <p className="eyebrow">Plan</p>
        <h2>{account?.plan_name || "Plan"}</h2>
      </div>
      {account && (
        <p className="lede tight">
          Memories are kept for {account.retention_label.toLowerCase()}. {usage}
          {subscription?.status === "past_due" ? " The last card payment failed." : ""}
          {cancelAt ? ` Renewal stops on ${formatWhen(cancelAt)}.` : ""}
          {subscription?.pending_change ? " A plan change is waiting on Stripe." : ""}
          {account.grant ? ` Memplug also granted ${account.grant.plan}${account.grant.until ? ` until ${formatWhen(account.grant.until)}` : ""}.` : ""}
        </p>
      )}
      {account?.products?.length ? (
        <div className="product-strip">
          {account.products.map((product) => (
            <article key={product.id} className={product.included ? "" : "dim"}>
              <h3>
                {product.name}
                {!product.available ? <span>Coming soon</span> : null}
                {product.included ? <span>Included</span> : <span>Not on this plan</span>}
              </h3>
              <p>{product.summary}</p>
            </article>
          ))}
        </div>
      ) : null}
      {account && !account.payments_ready && (
        <p className="notice status">Card checkout is waiting for STRIPE_SECRET_KEY on the server.</p>
      )}
      {(error || notice) && <p className={error ? "error status" : "notice status"}>{error || notice}</p>}
      <div className="plan-grid">
        {(account?.plans || []).map((plan) => {
          const current = account?.plan === plan.id;
          return (
            <article className={current ? "card current" : "card"} key={plan.id}>
              <header>
                <h3>{plan.name}</h3>
                <span>{current ? "current" : plan.period}</span>
              </header>
              <p className="amount">{plan.price_label}</p>
              <ul>
                {plan.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
              {current ? (
                cancelAt ? (
                  <button className="primary" type="button" disabled={Boolean(busy)} onClick={resume}>
                    {busy === "resume" ? "Resuming" : "Keep renewing"}
                  </button>
                ) : (
                  <button type="button" disabled>
                    Current plan
                  </button>
                )
              ) : (
                <button className="primary" type="button" disabled={Boolean(busy)} onClick={() => choose(plan)}>
                  {busy === plan.id
                    ? "Working"
                    : plan.id === "free"
                      ? "Stop renewing"
                      : `Upgrade to ${plan.name}`}
                </button>
              )}
            </article>
          );
        })}
      </div>
      {account?.teams?.length ? (
        <div className="team-usage">
          <h3>Team memory usage</h3>
          <p className="lede tight">Each team has its own daily fetch counter. The owner&apos;s Enterprise plan pays for it.</p>
          <ul>
            {account.teams.map((team) => (
              <li key={team.id}>
                <strong>{team.name}</strong>
                {team.active
                  ? ` · ${team.fetches_today} fetches today`
                  : ` · inactive · ${team.reason || "Enterprise required"}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {account?.can_manage && (
        <p className="hint">
          <button type="button" onClick={manage} disabled={busy === "portal"}>
            Manage card and invoices
          </button>
        </p>
      )}
      <form className="support-form" onSubmit={sendSupport}>
        <h3>{account?.priority_support ? "Priority support" : "Support"}</h3>
        <p>
          {account?.priority_support
            ? "Enterprise requests are marked priority and emailed to Memplug."
            : "Send a request from the console. Enterprise marks them as priority."}
        </p>
        <label>
          Subject
          <input value={subject} onChange={(event) => setSubject(event.target.value)} maxLength={120} required />
        </label>
        <label>
          Message
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} maxLength={5000} rows={4} required />
        </label>
        <button className="primary" type="submit" disabled={busy === "support"}>
          {busy === "support" ? "Sending" : "Send request"}
        </button>
      </form>
    </section>
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
  const [page, setPage] = useState(() => {
    const flag = new URLSearchParams(window.location.search).get("billing");
    return flag ? "plan" : "console";
  });

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
        <nav className="tabs" aria-label="Console">
          <button type="button" className={page === "console" ? "on" : ""} onClick={() => setPage("console")}>
            Console
          </button>
          <button type="button" className={page === "data" ? "on" : ""} onClick={() => setPage("data")}>
            Data
          </button>
          <button type="button" className={page === "plan" ? "on" : ""} onClick={() => setPage("plan")}>
            Plan
          </button>
          <button type="button" className={page === "docs" ? "on" : ""} onClick={() => setPage("docs")}>
            Docs
          </button>
        </nav>
        <div className="who">
          <a href={contactHref("Memplug issue")}>Contact</a>
          <span>{user.name || user.email}</span>
          <button type="button" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      {(error || notice) && <p className={error ? "error status" : "notice status"}>{error || notice}</p>}
      <main className="desk">
        {page === "plan" ? (
          <PlanView token={token} />
        ) : page === "data" ? (
          <DataView token={token} teams={teams} />
        ) : page === "docs" ? (
        <section className="band open" id="process">
          <div className="section-head">
            <p className="eyebrow">Docs</p>
            <h2>How to configure</h2>
          </div>
          <p className="lede tight">Connect this account to an editor. The controls stay on the Console tab.</p>
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
                  The agent does not send a user id. The key is the workspace. Paste the MCP config from the Console tab into Cursor.
                  Memories are written when a conversation crosses the token checkpoint, or after 30 minutes of
                  quiet. The raw chat stays. The memory is what the agent can search later.
                </p>
              </div>
            </li>
          </ol>
        </section>
        ) : (
        <>
        <section className="band open" id="workspaces">
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
                  <span>{item.role === "owner" ? "Owner" : "Member"}{item.active === false ? " · inactive" : ""}</span>
                  <strong>{item.name}</strong>
                  <p>
                    {item.active === false
                      ? item.reason || "Shared team memory needs an active Enterprise plan on the owner's account."
                      : `Team memory only. A key made while this card is open belongs to ${item.name}.`}
                  </p>
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
              <p>Shared team memory is Enterprise only. You become the owner, and the card shows a join code.</p>
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
        </>
        )}
      </main>
    </div>
  );
}
