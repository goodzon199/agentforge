"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { getToken } from "@/lib/api";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const isLogin = pathname === "/login";
  const authed = getToken();

  useEffect(() => {
    if (!isLogin && !authed) {
      router.replace("/login");
    }
  }, [isLogin, authed, router]);

  if (isLogin) {
    return <div className="h-full">{children}</div>;
  }

  if (!authed) {
    return null;
  }

  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 overflow-y-auto px-8 py-6">{children}</main>
    </div>
  );
}
