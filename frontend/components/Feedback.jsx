"use client";

import { useState } from "react";
import { rateAnswer } from "../lib/api";

export default function Feedback({ id, rating }) {
  const [value, setValue] = useState(rating ?? 0);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState(false);

  const send = (next, why) => {
    setValue(next);
    setSaved(false);
    rateAnswer(id, next, why)
      .then(() => setSaved(true))
      .catch(() => setValue(rating ?? 0));
  };

  return (
    <div className="feedback">
      <button
        type="button"
        className={`tab${value === 1 ? " on" : ""}`}
        aria-pressed={value === 1}
        onClick={() => {
          setAsking(false);
          send(1);
        }}
      >
        Helpful
      </button>
      <button
        type="button"
        className={`tab${value === -1 ? " on" : ""}`}
        aria-pressed={value === -1}
        onClick={() => setAsking(true)}
      >
        Not helpful
      </button>
      {asking ? (
        <form
          className="feedback__why"
          onSubmit={(e) => {
            e.preventDefault();
            setAsking(false);
            send(-1, reason.trim() || undefined);
          }}
        >
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            placeholder="What was wrong? (optional)"
            aria-label="What was wrong"
            autoFocus
          />
          <button type="submit" className="tab on">
            Send
          </button>
        </form>
      ) : (
        saved && <span className="feedback__saved">Thanks, noted</span>
      )}
    </div>
  );
}
