"use client";

export default function Error({ error, reset }) {
  return (
    <main className="auth">
      <div className="glass auth__card">
        <div className="auth__brand">
          <div className="brand__mark">P</div>
          <div>
            <h1>Something went wrong</h1>
            <p>The page hit an error. Your account and conversations are safe.</p>
          </div>
        </div>
        {error?.message && <div className="alert">{error.message}</div>}
        <button type="button" className="btn3 auth__submit" onClick={reset}>
          Try again
        </button>
      </div>
    </main>
  );
}
