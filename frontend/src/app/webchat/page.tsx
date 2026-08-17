"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type WidgetMessage = {
  id: string;
  sender_type: string;
  content: string;
  created_at: string;
};

type Started = {
  conversation_id: string;
  client_key: string;
  visitor_name: string;
  mode: string;
  status: string;
};

const KEY_LS = "agentforge_webchat_key";
const CONV_LS = "agentforge_webchat_conv";

export default function WebchatPage() {
  const [token, setToken] = useState<string>("");
  const [visitorName, setVisitorName] = useState("");
  const [started, setStarted] = useState(false);
  const [starting, setStarting] = useState(false);
  const [messages, setMessages] = useState<WidgetMessage[]>([]);
  const [mode, setMode] = useState<string>("ai_active");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const convIdRef = useRef<string | null>(null);
  const sentIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const t = params.get("token") ?? (process.env.NEXT_PUBLIC_WEBCHAT_TOKEN as string | undefined);
    if (t) setToken(t);
    const key = window.localStorage.getItem(KEY_LS);
    const conv = window.localStorage.getItem(CONV_LS);
    if (key && conv) {
      convIdRef.current = conv;
      setStarted(true);
    }
  }, []);

  const poll = useCallback(async (conversationId: string) => {
    try {
      const data = await api.get<{ conversation_id: string; mode: string; status: string; messages: WidgetMessage[] }>(
        `/public/chat/${conversationId}/messages`,
      );
      setMode(data.mode);
      setMessages((prev) => {
        const known = new Set(sentIds.current);
        const merged = new Map(prev.map((m) => [m.id, m]));
        for (const m of data.messages) {
          merged.set(m.id, m);
          known.add(m.id);
        }
        sentIds.current = known;
        return Array.from(merged.values());
      });
    } catch {
      // transient
    }
  }, []);

  useEffect(() => {
    if (!convIdRef.current) return;
    const timer = setInterval(() => poll(convIdRef.current!), 3000);
    return () => clearInterval(timer);
  }, [poll, started]);

  async function begin(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim() || starting) return;
    setStarting(true);
    setError(null);
    try {
      const key = window.localStorage.getItem(KEY_LS) ?? "";
      const res = await api.post<Started>("/public/chat/start", {
        public_token: token.trim(),
        visitor_name: visitorName.trim() || "Гость",
        client_key: key,
      });
      convIdRef.current = res.conversation_id;
      window.localStorage.setItem(KEY_LS, res.client_key);
      window.localStorage.setItem(CONV_LS, res.conversation_id);
      setMode(res.mode);
      setStarted(true);
      await poll(res.conversation_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось начать чат");
    } finally {
      setStarting(false);
    }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!convIdRef.current || !input.trim() || sending) return;
    setSending(true);
    try {
      const sent = await api.post<{ message: WidgetMessage; task_id: string | null }>(
        "/public/chat/messages",
        { conversation_id: convIdRef.current, content: input.trim() },
      );
      sentIds.current.add(sent.message.id);
      setMessages((prev) => [...prev, sent.message]);
      setInput("");
      setTimeout(() => poll(convIdRef.current!), 1500);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-slate-950 p-4">
      <div className="flex h-[min(720px,90vh)] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-surface-border bg-surface">
        <div className="border-b border-surface-border bg-surface-hover px-5 py-4">
          <div className="text-sm font-semibold text-white">Онлайн-чат</div>
          <div className="text-[11px] text-slate-500">
            {started
              ? mode === "human_active"
                ? "Сейчас с вами общается менеджер"
                : mode === "ai_active"
                  ? "Ассистент на связи — ответим быстро"
                  : "Чат на паузе — мы вернёмся к вам"
              : "Напишите нам — подберём запчасти"}
          </div>
        </div>

        <div className="flex-1 space-y-2 overflow-y-auto px-4 py-4">
          {!started ? (
            <form onSubmit={begin} className="space-y-3">
              <div className="text-xs text-slate-400">
                Демо-виджет публичного канала. Укажите имя и токен компании из README.
              </div>
              <input
                className="input"
                placeholder="Ваше имя"
                value={visitorName}
                onChange={(e) => setVisitorName(e.target.value)}
              />
              <input
                className="input font-mono"
                placeholder="public_token компании"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required
              />
              {error ? <div className="text-xs text-rose-400">{error}</div> : null}
              <button type="submit" className="btn-primary w-full" disabled={starting}>
                {starting ? "Подключение…" : "Начать чат"}
              </button>
            </form>
          ) : messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-xs text-slate-600">
              Напишите первым сообщение — например, «Нужны передние колодки на BMW X5 2019».
            </div>
          ) : (
            messages.map((m) => (
              <div
                key={m.id}
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  m.sender_type === "customer"
                    ? "ml-auto bg-accent/90 text-white"
                    : "bg-surface-hover text-slate-200"
                }`}
              >
                {m.content}
                <div className={`mt-1 text-[10px] ${m.sender_type === "customer" ? "text-white/70" : "text-slate-500"}`}>
                  {m.sender_type === "customer" ? "вы" : m.sender_type}
                </div>
              </div>
            ))
          )}
        </div>

        <form onSubmit={send} className="flex gap-2 border-t border-surface-border p-3">
          <input
            className="input flex-1"
            placeholder="Сообщение…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!started}
          />
          <button type="submit" className="btn-primary" disabled={!started || !input.trim() || sending}>
            Отправить
          </button>
        </form>
      </div>
    </div>
  );
}
