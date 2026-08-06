"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken, TOKEN_KEY } from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.post<LoginResponse>("/auth/login", { email, password });
      setToken(res.access_token);
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-accent text-xl font-bold text-white">
            AF
          </div>
          <h1 className="text-xl font-semibold text-white">AgentForge</h1>
          <p className="mt-1 text-sm text-slate-500">Digital Workforce OS — вход</p>
        </div>

        <form onSubmit={submit} className="card">
          <label className="mb-1 block text-xs text-slate-500">E-mail</label>
          <input
            type="email"
            className="input mb-3"
            placeholder="admin@agentos.local"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <label className="mb-1 block text-xs text-slate-500">Пароль</label>
          <input
            type="password"
            className="input mb-4"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit" className="btn-primary w-full" disabled={submitting}>
            {submitting ? "Входим…" : "Войти"}
          </button>
          {error ? <div className="mt-3 text-xs text-rose-400">{error}</div> : null}
        </form>

        <p className="mt-4 text-center text-xs text-slate-600">
          Демо-доступ: admin@agentos.local / admin123
        </p>
      </div>
    </div>
  );
}
