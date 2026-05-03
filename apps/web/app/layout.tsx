import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI+测试平台",
  description: "面向接口测试与 UI 测试的 AI 工作台。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                let theme = localStorage.getItem('app-theme') || 'green';
                document.documentElement.setAttribute('data-theme', theme);
              } catch (_) {}
            `,
          }}
        />
      </head>
      <body
        className="flex min-h-full flex-col bg-brand-gray text-brand-black selection:bg-brand-green/20"
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
