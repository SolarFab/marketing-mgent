"use client";
// The persistent shell: header, tab bar down the left, chat rail on the right.
// Every page renders inside the middle column. See docs/architecture.md.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChatRail } from "./ChatRail";

const TABS = [
  { href: "/", label: "Review", hint: "Curation queue" },
  { href: "/sources", label: "Sources", hint: "What we read" },
  { href: "/newsletter", label: "Newsletter", hint: "Drafts + layout" },
  { href: "/social", label: "Social", hint: "IG + LinkedIn" },
  { href: "/profile", label: "Profile", hint: "Voice + learned rules" },
  { href: "/analytics", label: "Analytics", hint: "Approval + eval" },
  { href: "/onboard", label: "Onboard", hint: "First-run flow" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen grid grid-cols-[220px_1fr_360px]">
      {/* Left: nav */}
      <aside className="border-r border-neutral-200 bg-white px-4 py-5">
        <div className="mb-6">
          <div className="text-lg font-semibold tracking-tight">Signal</div>
          <div className="text-xs text-neutral-500">Content Agent</div>
        </div>
        <nav className="flex flex-col gap-1">
          {TABS.map((t) => {
            const active =
              pathname === t.href ||
              (t.href !== "/" && pathname.startsWith(t.href));
            return (
              <Link
                key={t.href}
                href={t.href}
                className={`rounded-md px-3 py-2 text-sm transition ${
                  active
                    ? "bg-neutral-900 text-white"
                    : "text-neutral-700 hover:bg-neutral-100"
                }`}
              >
                <div>{t.label}</div>
                <div className={`text-[11px] ${active ? "text-neutral-300" : "text-neutral-400"}`}>
                  {t.hint}
                </div>
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Middle: page content */}
      <main className="px-8 py-6 overflow-y-auto">{children}</main>

      {/* Right: chat rail */}
      <aside className="border-l border-neutral-200 bg-white">
        <ChatRail />
      </aside>
    </div>
  );
}
