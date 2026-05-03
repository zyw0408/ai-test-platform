"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ClipboardList,
  FileCheck2,
  Network,
  Activity,
  ShieldAlert,
  FileText,
  TerminalSquare,
  Settings
} from "lucide-react";

export function AppNav({ dict, lang }: { dict: any, lang: string }) {
  const pathname = usePathname();

  const items = [
    { href: "/", label: dict.requirements, icon: ClipboardList },
    { href: "/cases", label: dict.testCases, icon: FileCheck2 },
    { href: "/api-tests", label: dict.apiTesting, icon: Network },
    { href: "/auto-tests", label: dict.automatedTesting, icon: TerminalSquare },
    { href: "/performance", label: dict.performance, icon: Activity },
    { href: "/security", label: dict.security, icon: ShieldAlert },
    { href: "/reports", label: dict.reports, icon: FileText },
    { href: "/settings", label: "系统设置", icon: Settings },
  ] as const;

  return (
    <aside className="workspace-sidebar">
      <div className="sidebar-shell">
        <div className="sidebar-brand" style={{ marginBottom: "20px" }}>
          <div className="brand-mark">AI</div>
          <div>
            <div className="brand-name">AI Testing</div>
            <div className="brand-subtitle">Console Engine</div>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Primary">
          {items.map((item) => {
            const Icon = item.icon;
            const isActive =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href));

            return (
              <Link
                key={`${item.href}-${item.label}`}
                href={item.href as any}
                className={`sidebar-link ${isActive ? "is-active" : ""}`}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon size={18} strokeWidth={1.8} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
