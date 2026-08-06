"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type {
  Company,
  Conversation,
  ConversationDetail,
  ConversationMessage,
  Customer,
  MessageSent,
  PartRequest,
} from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";
import { PartRequestPanel } from "@/components/conversations/PartRequestPanel";

export default function ConversationsPage() {
  const { data: conversations, loading, error, reload, setData } = useApi<Conversation[]>("/conversations");
  const { data: companies } = useApi<Company[]>("/companies");

  const [selected, setSelected] = useState<ConversationDetail | null>(null);
  const [partRequests, setPartRequests] = useState<PartRequest[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  // Create-customer form
  const [showNew, setShowNew] = useState(false);
  const [companyId, setCompanyId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (companies && companies.length && !companyId) setCompanyId(companies[0].id);
  }, [companies, companyId]);

  async function loadPartRequests(conversationId: string) {
    try {
      const requests = await api.get<PartRequest[]>(`/part_requests?conversation_id=${conversationId}`);
      setPartRequests(requests);
    } catch {
      setPartRequests([]);
    }
  }

  async function selectConversation(id: string) {
    const detail = await api.get<ConversationDetail>(`/conversations/${id}`);
    setSelected(detail);
    await loadPartRequests(id);
  }

  async function openConversation(c: Conversation) {
    await selectConversation(c.id);
  }

  // Poll the open conversation so IntakeAgent replies and PartRequest
  // updates appear without a manual refresh.
  useEffect(() => {
    if (!selected) return;
    const timer = setInterval(async () => {
      try {
        const detail = await api.get<ConversationDetail>(`/conversations/${selected.id}`);
        setSelected(detail);
        await loadPartRequests(selected.id);
      } catch {
        // ignore transient errors
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [selected?.id]);

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || !draft.trim() || sending) return;
    setSending(true);
    try {
      const sent = await api.post<MessageSent>(`/conversations/${selected.id}/messages`, {
        sender_type: "customer",
        content: draft.trim(),
      });
      setSelected({
        ...selected,
        messages: [...selected.messages, sent.message],
        updated_at: new Date().toISOString(),
      });
      setDraft("");
      await reload();
      await loadPartRequests(selected.id);
      // In live mode IntakeAgent runs in a worker; catch up shortly after.
      setTimeout(async () => {
        const detail = await api.get<ConversationDetail>(`/conversations/${selected.id}`);
        setSelected(detail);
        await loadPartRequests(selected.id);
      }, 1500);
    } finally {
      setSending(false);
    }
  }

  async function createCustomerAndConversation(e: React.FormEvent) {
    e.preventDefault();
    if (!companyId || !customerName.trim() || busy) return;
    setBusy(true);
    try {
      const customer = await api.post<Customer>("/customers", {
        company_id: companyId,
        name: customerName.trim(),
        phone,
        email,
        source: "web",
      });
      const conversation = await api.post<Conversation>("/conversations", {
        company_id: companyId,
        customer_id: customer.id,
        channel: "web",
      });
      setShowNew(false);
      setCustomerName("");
      setPhone("");
      setEmail("");
      await reload();
      setData([conversation, ...(conversations ?? [])]);
      await selectConversation(conversation.id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <SectionHeader
        title="Диалоги"
        action={
          <button className="btn-primary" onClick={() => setShowNew((v) => !v)}>
            + Новый диалог
          </button>
        }
      />

      {showNew ? (
        <form onSubmit={createCustomerAndConversation} className="card mb-5">
          <h2 className="mb-3 text-sm font-medium text-slate-300">Новый клиент и диалог</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <select className="input" value={companyId} onChange={(e) => setCompanyId(e.target.value)} required>
              {companies?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <input
              className="input"
              placeholder="Имя клиента"
              value={customerName}
              onChange={(e) => setCustomerName(e.target.value)}
              required
            />
            <input className="input" placeholder="Телефон" value={phone} onChange={(e) => setPhone(e.target.value)} />
            <input className="input" placeholder="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="mt-3 flex justify-end">
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? "Создаём…" : "Создать"}
            </button>
          </div>
        </form>
      ) : null}

      <div className="grid h-[calc(100vh-190px)] gap-4 lg:grid-cols-[320px_1fr]">
        <div className="card flex flex-col overflow-hidden p-0">
          {loading ? (
            <div className="p-4"><Loading /></div>
          ) : error ? (
            <div className="p-4"><ErrorBox message={error} /></div>
          ) : conversations && conversations.length === 0 ? (
            <div className="p-4">
              <EmptyState title="Диалогов пока нет" description="Создайте первый диалог — клиент напишет запрос на запчасть." />
            </div>
          ) : (
            <div className="divide-y divide-surface-border overflow-y-auto">
              {conversations?.map((c) => (
                <button
                  key={c.id}
                  onClick={() => openConversation(c)}
                  className={`block w-full px-4 py-3 text-left transition hover:bg-surface-hover ${
                    selected?.id === c.id ? "bg-surface-hover" : ""
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="truncate text-sm font-medium text-white">{c.customer_name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-slate-500">
                    {c.channel} · {new Date(c.updated_at).toLocaleString("ru-RU")}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="card flex flex-col p-0">
          {selected ? (
            <>
              <div className="border-b border-surface-border px-5 py-3">
                <div className="text-sm font-semibold text-white">{selected.customer_name}</div>
                <div className="text-xs text-slate-500">
                  Диалог · {selected.channel} · обновлён {new Date(selected.updated_at).toLocaleString("ru-RU")}
                </div>
              </div>

              <div className="border-b border-surface-border px-5 py-3">
                <PartRequestPanel partRequests={partRequests} />
              </div>

              <div className="flex-1 space-y-2 overflow-y-auto px-5 py-4">
                {selected.messages.length === 0 ? (
                  <div className="text-center text-xs text-slate-600">Сообщений пока нет — напишите первым.</div>
                ) : (
                  selected.messages.map((m: ConversationMessage) => (
                    <div
                      key={m.id}
                      className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                        m.sender_type === "customer"
                          ? "ml-auto bg-accent/90 text-white"
                          : "bg-surface text-slate-200"
                      }`}
                    >
                      {m.content}
                      <div className={`mt-1 text-[10px] ${m.sender_type === "customer" ? "text-white/70" : "text-slate-500"}`}>
                        {m.sender_type}
                        {m.task_id ? " · задача создана" : ""}
                      </div>
                    </div>
                  ))
                )}
              </div>

              <form onSubmit={sendMessage} className="flex gap-2 border-t border-surface-border p-3">
                <input
                  className="input flex-1"
                  placeholder="Например: Нужны передние колодки на BMW X5 2019"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <button type="submit" className="btn-primary" disabled={sending || !draft.trim()}>
                  Отправить
                </button>
              </form>
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-600">
              Выберите диалог слева или создайте новый
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
