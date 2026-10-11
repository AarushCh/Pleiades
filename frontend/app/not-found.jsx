export default function NotFound() {
  return (
    <main className="auth">
      <div className="glass auth__card">
        <div className="auth__brand">
          <div className="brand__mark">P</div>
          <div>
            <h1>Page not found</h1>
            <p>That address isn't part of Pleiades.</p>
          </div>
        </div>
        <a className="btn3 auth__submit" href="/">
          Back to Pleiades
        </a>
      </div>
    </main>
  );
}
