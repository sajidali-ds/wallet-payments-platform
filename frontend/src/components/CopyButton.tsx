import { useState } from "react";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable (plain HTTP): the value is still selectable text.
    }
  }

  return (
    <button type="button" className="link-button" onClick={copy}>
      {copied ? "Copied" : label}
    </button>
  );
}
