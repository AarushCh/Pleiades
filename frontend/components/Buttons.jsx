"use client";

export function Btn3({ variant, size, className = "", children, ...rest }) {
  const classes = ["btn3"];
  if (variant) classes.push(`btn3--${variant}`);
  if (size) classes.push(`btn3--${size}`);
  if (className) classes.push(className);
  return (
    <button type="button" className={classes.join(" ")} {...rest}>
      {children}
    </button>
  );
}

export function Btn12({ title, note, ...rest }) {
  return (
    <button type="button" className="btn12" {...rest}>
      <span className="btn12__rule" aria-hidden="true" />
      <span className="btn12__title">{title}</span>
      {note && <span className="btn12__note">{note}</span>}
    </button>
  );
}
