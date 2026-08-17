"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type {
  Approval,
  Company,
  Conversation,
  ConversationDetail,
  ConversationMessage,
  Customer,
  MessageSent,
  Order,
  OrderCreateResult,
  PartQuote,
  PartRequest,
  QuoteSendResult,
  SalesDraft,
  ShadowComparison,
  ShadowList,
  SupplierOffer,
  SupplierSearchRun,
} from "@/lib/types";
import { EmptyState, ErrorBox, Loading, SectionHeader, StatusBadge } from "@/components/ui";
import { PartRequestPanel } from "@/components/conversations/PartRequestPanel";
import { QuoteSalesPanel } from "@/components/conversations/QuoteSalesPanel";
import { ShadowPanel } from "@/components/conversations/ShadowPanel";

const ACTIVE_STATUSES = ["collecting_data", "ready_for_search", "searching", "quoted"];

const MODE_LABEL: Record<string, string> = {
  ai_active: "AI",
  human_active: "Менеджер",
  paused: "Пауза",
  closed: "Закрыт",
};

function ModeBadge({ mode }: { mode: string }) {
  const cls =
    mode === "human_active"
      ? "bg-amber-500/15 text-amber-400"
      : mode === "paused"
        ? "bg-slate-500/15 text-slate-400"
        : mode === "closed"
          ? "bg-rose-500/15 text-rose-400"
          : "bg-emerald-500/15 text-emerald-400";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {MODE_LABEL[mode] ?? mode}
    </span>
  );
}

function activePartRequest(partRequests: PartRequest[]): PartRequest | undefined {
  return (
    partRequests.find((pr) => ACTIVE_STATUSES.includes(pr.status)) ?? partRequests[0]
  );
}

export default function ConversationsPage() {
  const searchParams = useSearchParams();
  const { data: conversations, loading, error, reload, setData } = useApi<Conversation[]>("/conversations");
  const { data: companies } = useApi<Company[]>("/companies");

  const [selected, setSelected] = useState<ConversationDetail | null>(null);
  const [partRequests, setPartRequests] = useState<PartRequest[]>([]);
  const [offers, setOffers] = useState<SupplierOffer[]>([]);
  const [searchRuns, setSearchRuns] = useState<SupplierSearchRun[]>([]);
  const [quote, setQuote] = useState<PartQuote | null>(null);
  const [searching, setSearching] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [salesDraft, setSalesDraft] = useState<SalesDraft | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [salesBusy, setSalesBusy] = useState(false);
  const [shadow, setShadow] = useState<ShadowList | null>(null);

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

  useEffect(() => {
    const openId = searchParams.get("open");
    if (!openId || !conversations || conversations.length === 0 || selected) return;
    const target = conversations.find((c) => c.id === openId);
    if (target) void openConversation(target);
  }, [searchParams, conversations, selected]);

  async function loadSearchData(requests: PartRequest[]) {
    const active = activePartRequest(requests);
    if (!active) {
      setOffers([]);
      setSearchRuns([]);
      setQuote(null);
      setSalesDraft(null);
      setApprovals([]);
      setOrders([]);
      return;
    }
    try {
      const [loadedOffers, loadedRuns, loadedQuote, loadedApprovals, loadedOrders] =
        await Promise.all([
          api.get<SupplierOffer[]>(`/part_requests/${active.id}/offers`),
          api.get<SupplierSearchRun[]>(`/part_requests/${active.id}/search-runs`),
          api.get<PartQuote>(`/part_requests/${active.id}/quote`),
          api.get<Approval[]>("/approvals"),
          api.get<Order[]>("/orders"),
        ]);
      setOffers(loadedOffers);
      setSearchRuns(loadedRuns);
      setQuote(loadedQuote);
      setApprovals(loadedApprovals);
      setOrders(loadedOrders);
      if (loadedQuote?.quote_id) {
        try {
          const loadedDraft = await api.get<SalesDraft>(
            `/quotes/${loadedQuote.quote_id}/sales-draft`,
          );
          setSalesDraft(loadedDraft);
        } catch {
          setSalesDraft(null);
        }
      } else {
        setSalesDraft(null);
      }
    } catch {
      setOffers([]);
      setSearchRuns([]);
      setQuote(null);
      setSalesDraft(null);
      setApprovals([]);
      setOrders([]);
    }
  }

  async function loadShadow() {
    try {
      setShadow(await api.get<ShadowList>("/manager/shadow?limit=50"));
    } catch {
      setShadow(null);
    }
  }

  async function loadPartRequests(conversationId: string) {
    try {
      const requests = await api.get<PartRequest[]>(`/part_requests?conversation_id=${conversationId}`);
      setPartRequests(requests);
      await loadSearchData(requests);
    } catch {
      setPartRequests([]);
    }
  }

  async function runSearch(partRequestId: string) {
    if (searching) return;
    setSearching(true);
    try {
      await api.post(`/part_requests/${partRequestId}/search`, {});
      await loadPartRequests(selected!.id);
    } finally {
      setSearching(false);
    }
  }

  const currentApproval: Approval | null = salesDraft
    ? approvals.find((a) => a.quote_id === salesDraft.quote_id) ?? null
    : null;

  const currentOrder: Order | null = salesDraft
    ? orders.find((o) => o.quote_id === salesDraft.quote_id) ?? null
    : null;

  const activeRequest = activePartRequest(partRequests);
  const currentComparison: ShadowComparison | null = shadow
    ? shadow.items.find((c) => c.part_request_id === activeRequest?.id) ?? null
    : null;

  async function sendForApproval(message: string, approveNow = false) {
    if (!salesDraft || salesBusy) return;
    setSalesBusy(true);
    try {
      const result = await api.post<QuoteSendResult>(
        `/quotes/${salesDraft.quote_id}/send`,
        { message, approve_now: approveNow },
      );
      await loadPartRequests(selected!.id);
    } finally {
      setSalesBusy(false);
    }
  }

  async function approveQuote(approvalId: string) {
    if (salesBusy) return;
    setSalesBusy(true);
    try {
      await api.post(`/approvals/${approvalId}/approve`, {});
      await loadPartRequests(selected!.id);
      await api.get<ConversationDetail>(`/conversations/${selected!.id}`).then(setSelected);
    } finally {
      setSalesBusy(false);
    }
  }

  async function rejectQuote(approvalId: string) {
    if (salesBusy) return;
    setSalesBusy(true);
    try {
      await api.post(`/approvals/${approvalId}/reject`, { rejection_reason: "Отклонено менеджером" });
      await loadPartRequests(selected!.id);
    } finally {
      setSalesBusy(false);
    }
  }

  async function acceptQuote() {
    if (!salesDraft || salesBusy) return;
    setSalesBusy(true);
    try {
      await api.post(`/quotes/${salesDraft.quote_id}/accept`, {});
      await loadPartRequests(selected!.id);
    } finally {
      setSalesBusy(false);
    }
  }

  async function convertQuote() {
    if (!salesDraft || salesBusy) return;
    setSalesBusy(true);
    try {
      const result = await api.post<OrderCreateResult>(`/quotes/${salesDraft.quote_id}/convert`, {});
      await loadPartRequests(selected!.id);
      await api.get<ConversationDetail>(`/conversations/${selected!.id}`).then(setSelected);
    } finally {
      setSalesBusy(false);
    }
  }

  const [modeBusy, setModeBusy] = useState(false);
  const [asManager, setAsManager] = useState(false);

  async function changeMode(action: "takeover" | "release" | "pause" | "close" | "reopen") {
    if (!selected || modeBusy) return;
    setModeBusy(true);
    try {
      const updated = await api.post<Conversation>(`/conversations/${selected.id}/${action}`, {});
      await reload();
      await api.get<ConversationDetail>(`/conversations/${selected.id}`).then((d) => {
        setSelected(d);
      });
    } finally {
      setModeBusy(false);
    }
  }

  async function selectConversation(id: string) {
    const detail = await api.get<ConversationDetail>(`/conversations/${id}`);
    setSelected(detail);
    await loadPartRequests(id);
    void loadShadow();
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
        void loadShadow();
      } catch {
        // ignore transient errors
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [selected?.id]);

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || !draft.trim() || sending) return;
    const senderType = selected.mode === "human_active" || asManager ? "manager" : "customer";
    setSending(true);
    try {
      const sent = await api.post<MessageSent>(`/conversations/${selected.id}/messages`, {
        sender_type: senderType,
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
                    <span className="flex items-center gap-1.5">
                      <ModeBadge mode={c.mode} />
                      <StatusBadge status={c.status} />
                    </span>
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
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-white">{selected.customer_name}</div>
                    <div className="text-xs text-slate-500">
                      Диалог · {selected.channel} · обновлён {new Date(selected.updated_at).toLocaleString("ru-RU")}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <ModeBadge mode={selected.mode} />
                    {selected.mode === "ai_active" ? (
                      <>
                        <button className="btn-ghost" onClick={() => changeMode("takeover")} disabled={modeBusy}>
                          Перехватить диалог
                        </button>
                        <button className="btn-ghost" onClick={() => changeMode("pause")} disabled={modeBusy}>
                          Пауза
                        </button>
                        <button className="btn-ghost" onClick={() => changeMode("close")} disabled={modeBusy}>
                          Закрыть
                        </button>
                      </>
                    ) : null}
                    {selected.mode === "human_active" ? (
                      <>
                        <button className="btn-primary" onClick={() => changeMode("release")} disabled={modeBusy}>
                          Вернуть AI
                        </button>
                        <button className="btn-ghost" onClick={() => changeMode("close")} disabled={modeBusy}>
                          Закрыть
                        </button>
                      </>
                    ) : null}
                    {selected.mode === "paused" ? (
                      <>
                        <button className="btn-primary" onClick={() => changeMode("release")} disabled={modeBusy}>
                          Вернуть AI
                        </button>
                        <button className="btn-ghost" onClick={() => changeMode("takeover")} disabled={modeBusy}>
                          Перехватить
                        </button>
                        <button className="btn-ghost" onClick={() => changeMode("close")} disabled={modeBusy}>
                          Закрыть
                        </button>
                      </>
                    ) : null}
                    {selected.mode === "closed" ? (
                      <button className="btn-ghost" onClick={() => changeMode("reopen")} disabled={modeBusy}>
                        Возобновить
                      </button>
                    ) : null}
                  </div>
                </div>
                {selected.mode !== "ai_active" ? (
                  <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                    {selected.mode === "human_active"
                      ? "AI-агент не отвечает — диалог ведёт менеджер. Сообщения ниже отправляются от имени менеджера."
                      : selected.mode === "paused"
                        ? "Диалог на паузе: ни AI, ни клиент не получают автодействий."
                        : "Диалог закрыт: AI не отвечает, пока вы не возобновите его."}
                  </div>
                ) : null}
              </div>

              <div className="border-b border-surface-border px-5 py-3">
                <PartRequestPanel
                  partRequests={partRequests}
                  offers={offers}
                  searchRuns={searchRuns}
                  quote={quote}
                  searching={searching}
                  onSearch={runSearch}
                />
                <QuoteSalesPanel
                  draft={salesDraft}
                  approval={currentApproval}
                  order={currentOrder}
                  busy={salesBusy}
                  onSend={sendForApproval}
                  onSendNow={(m) => sendForApproval(m, true)}
                  onApprove={approveQuote}
                  onReject={rejectQuote}
                  onAccept={acceptQuote}
                  onConvert={convertQuote}
                />
                {activeRequest ? (
                  <ShadowPanel
                    partRequestId={activeRequest.id}
                    comparison={currentComparison}
                    onSubmitted={() => {
                      void loadShadow();
                      if (selected) void loadPartRequests(selected.id);
                    }}
                  />
                ) : null}
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
                <div className="flex flex-col">
                  <button
                    type="button"
                    className={`rounded px-2 py-1 text-[11px] font-medium ${
                      asManager || selected.mode === "human_active"
                        ? "bg-accent/20 text-accent-soft"
                        : "bg-surface text-slate-400 hover:bg-surface-hover"
                    }`}
                    onClick={() => setAsManager((v) => !v)}
                    title="Отправить сообщение от имени менеджера"
                  >
                    {asManager || selected.mode === "human_active" ? "Менеджер" : "Клиент"}
                  </button>
                </div>
                <input
                  className="input flex-1"
                  placeholder={
                    selected.mode === "human_active"
                      ? "Ответ клиенту от менеджера…"
                      : "Например: Нужны передние колодки на BMW X5 2019"
                  }
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
