import { useState } from "react";

export default function LoginScreen({ onLogin, error, busy }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  return (
    <div className="login-screen">
      <form
        className="login-form"
        onSubmit={(e) => {
          e.preventDefault();
          onLogin(username, password);
        }}
      >
        <h1>CREXi Workshop Assistant</h1>
        <label>Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <label>Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="login-error">{error}</div>}
        <button className="btn btn-confirm" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
