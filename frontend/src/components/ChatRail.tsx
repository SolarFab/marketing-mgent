"use client";
// The persistent right-hand chat rail. Calls POST /chat and renders both the
// user message and the agent's reply. Also renders a small "did action X"
// affordance below the reply for successful side effects.

import { useState } from "react";
import { api } from "@/lib/api";

type Msg = {
  who: "you" | "agent";
  text: string;
  meta?: { action?: string; note?: string };
};

export function ChatRail() {
  const [history, setHistory] = useState<Msg[]>([
    {
      who: "agent",
      text:
        "Hi. I'm your content agent. Ask me things like: 'find more sources on autonomous driving', 'why did you reject c_017?', or 'post more about our own products'.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    const text = input.trim();
    if (!text) return;
    setBusy(true);
    setInput("");
    setHistory((h) => [...h, { who: "you", text }]);
    try {
      const r = await api.chat(text);
      setHistory((h) => [
        ...h,
        { who: "agent", text: r.reply, meta: { action: r.action, note: r.note } },
      ]);
    } catch (e: any) {
      setHistory((h) => [
        ...h,
        { who: "agent", text: `Error: ${e.message || String(e)}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-neutral-200 px-4 py-3">
        <div className="text-sm font-semibold">Orchestrator</div>
        <div className="text-[11px] text-neutral-500">Steer without leaving the tab.</div>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {history.map((m, i) => (
          <div
            key={i}
            className={`text-sm whitespace-pre-wrap ${
              m.who === "you" ? "text-neutral-900" : "text-neutral-700"
            }`}
          >
            <div className="text-[10px] uppercase tracking-wider text-neutral-400">
              {m.who === "you" ? "You" : "Agent"}
            </div>
            <div>{m.text}</div>
            {m.meta?.action && m.meta.action !== "chat" && (
              <div className="mt-1 text-[10px] text-neutral-500 italic">
                → action: {m.meta.action}
                {m.meta.note ? ` — ${m.meta.note}` : ""}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="text-xs text-neutral-500">Thinking…</div>}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="border-t border-neutral-200 p-3"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
          placeholder="Type a command or a question…"
          className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-neutral-500"
        />
      </form>
    </div>
  );
}
