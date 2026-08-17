"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, USER_KEY } from "@/lib/api";
import { getStoredUser } from "@/lib/api";

export default function ChangePasswordPage() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const user = getStoredUser<{ email?: string }>();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError("Пароли не совпадают.");
      return;
    }
    if (next.length < 8) {
      setError("Пароль должен быть не короче 8 символов.");
      return;
    }
    setSubmitting(true);
    try {
      const updated = await api.post<{ must_change_password: boolean }>(
        "/auth/change-password",
        { current_password: current, new_password: next },
      );
      window.localStorage.setItem(
        USER_KEY,
        JSON.stringify({ ...user, must_change_password: updated.must_change_password }),
      );
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сменить пароль");
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
          <h1 className="text-xl font-semibold text-white">Смена пароля</h1>
          <p className="mt-1 text-sm text-slate-500">
            Требуется смена пароля при первом входе
          </p>
        </div>

        <form onSubmit={submit} className="card">
          <label className="mb-1 block text-xs text-slate-500">Текущий пароль</label>
          <input
            type="password"
            className="input mb-3"
            placeholder="••••••••"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
            autoFocus
          />
          <label className="mb-1 block text-xs text-slate-500">Новый пароль</label>
          <input
            type="password"
            className="input mb-3"
            placeholder="Минимум 8 символов"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
          <label className="mb-1 block text-xs text-slate-500">Повторите новый пароль</label>
          <input
            type="password"
            className="input mb-4"
            placeholder="••••••••"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          <button type="submit" className="btn-primary w-full" disabled={submitting}>
            {submitting ? "Сохраняем…" : "Сменить пароль"}
          </button>
          {error ? <div className="mt-3 text-xs text-rose-400">{error}</div> : null}
        </form>

        <button
          type="button"
          className="mt-4 block w-full text-center text-xs text-slate-600 hover:text-slate-400"
          onClick={() => {
            clearToken();
            router.replace("/login");
          }}
        >
          Выйти
        </button>
      </div>
    </div>
  );
}
