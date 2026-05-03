"use client";

import type { CSSProperties, ReactNode } from "react";

type PageHeaderProps = {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  tags?: string[];
  style?: CSSProperties;
};

export function PageHeader({ icon, title, subtitle, tags = [], style }: PageHeaderProps) {
  return (
    <header className="page-header" style={style}>
      <div className="page-header-main">
        {icon ? <span className="page-header-icon">{icon}</span> : null}
        <div style={{ minWidth: 0 }}>
          <h1 className="page-header-title">{title}</h1>
          {subtitle ? <p className="page-header-subtitle">{subtitle}</p> : null}
        </div>
      </div>
      {tags.length > 0 ? (
        <div className="page-header-tags">
          {tags.map((tag) => (
            <span key={tag} className="signal-pill">
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </header>
  );
}
