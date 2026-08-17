"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { getToken } from "@/lib/api";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const isLogin = pathname === "/login";
  const isPublic = pathname.startsWith("/webchat");
  const isBare = isLogin || isPublic || pathname.startsWith("/change-password");
  const authed = getToken();

  useEffect(() => {
    if (!isBare && !authed) {
      router.replace("/login");
    }
  }, [isBare, authed, router]);

  if (isBare) {
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
