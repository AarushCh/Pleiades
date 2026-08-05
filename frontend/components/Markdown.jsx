"use client";

function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={i}>{part.slice(1, -1)}</code>;
    }
    return <span key={i}>{part}</span>;
  });
}

export default function Markdown({ text }) {
  const blocks = text.split(/\n{2,}/);

  return blocks.map((block, i) => {
    const lines = block.split("\n").filter(Boolean);
    if (!lines.length) return null;

    if (lines.length > 1 && lines.every((l) => /^\s*\|/.test(l))) {
      const rows = lines
        .filter((l) => !/^\s*\|[\s|:-]+\|\s*$/.test(l))
        .map((l) =>
          l
            .trim()
            .replace(/^\||\|$/g, "")
            .split("|")
            .map((c) => c.trim())
        );
      const [head, ...body] = rows;
      return (
        <table className="md-table" key={i}>
          <thead>
            <tr>
              {head.map((c, j) => (
                <th key={j}>{inline(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, j) => (
              <tr key={j}>
                {row.map((c, k) => (
                  <td key={k}>{inline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    if (lines.every((l) => /^\s*(\d+\.|[-*])\s+/.test(l))) {
      const ordered = /^\s*\d+\./.test(lines[0]);
      const items = lines.map((l) => l.replace(/^\s*(\d+\.|[-*])\s+/, ""));
      const List = ordered ? "ol" : "ul";
      return (
        <List key={i}>
          {items.map((item, j) => (
            <li key={j}>{inline(item)}</li>
          ))}
        </List>
      );
    }

    return <p key={i}>{inline(block)}</p>;
  });
}
