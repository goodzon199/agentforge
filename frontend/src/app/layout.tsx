import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "AgentForge — Digital Workforce OS",
  description: "Операционная система для цифровых сотрудников.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body className="h-screen overflow-hidden">
        <div className="flex h-full">
          <Sidebar />
          <main className="flex-1 overflow-y-auto px-8 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
