"use client";

import { useState } from "react";
import { Btn3 } from "./Buttons";
import { login, signup, writeSession } from "../lib/api";

export default function AuthGate({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = isSignup
        ? form
        : { email: form.email, password: form.password };
      const session = await (isSignup ? signup(payload) : login(payload));
      writeSession(session);
      onAuthenticated(session);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <form className="glass auth__card" onSubmit={submit}>
        <div className="auth__brand">
          <div className="brand__mark">P</div>
          <div>
            <h1>Palades</h1>
            <p>Enterprise support intelligence</p>
          </div>
        </div>

        <div className="auth__switch" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={!isSignup}
            className={`tab ${!isSignup ? "on" : ""}`}
            onClick={() => setMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isSignup}
            className={`tab ${isSignup ? "on" : ""}`}
            onClick={() => setMode("signup")}
          >
            Create account
          </button>
        </div>

        {isSignup && (
          <label className="field">
            <span>Name</span>
            <input value={form.name} onChange={set("name")} required maxLength={120} />
          </label>
        )}

        <label className="field">
          <span>Email</span>
          <input type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={form.password}
            onChange={set("password")}
            required
            minLength={8}
            autoComplete={isSignup ? "new-password" : "current-password"}
          />
          {isSignup && <small>At least 8 characters</small>}
        </label>

        {error && <div className="alert">{error}</div>}

        <Btn3 type="submit" disabled={busy} className="auth__submit">
          {busy ? "Working" : isSignup ? "Create account" : "Sign in"}
        </Btn3>
      </form>
    </div>
  );
}
