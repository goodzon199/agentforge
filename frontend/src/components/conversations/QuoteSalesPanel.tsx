import { useEffect, useState } from "react";
import type { Approval, Order, SalesDraft } from "@/lib/types";
import { getStoredUser } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  draft: "Черновик предложения",
  pending_approval: "На согласовании",
  sent: "Отправлено клиенту",
  accepted: "Клиент принял",
  rejected: "Отклонено",
  expired: "Истёк срок согласования",
  converted_to_order: "Конвертирован в заказ",
};

function formatPrice(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(num);
}

type Props = {
  draft: SalesDraft | null;
  approval: Approval | null;
  order: Order | null;
  busy: boolean;
  onSend: (message: string) => void;
  onSendNow: (message: string) => void;
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
  onAccept: () => void;
  onConvert: () => void;
};

export function QuoteSalesPanel({
  draft,
  approval,
  order,
  busy,
  onSend,
  onSendNow,
  onApprove,
  onReject,
  onAccept,
  onConvert,
}: Props) {
  const [text, setText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const isManager = getStoredUser<{ is_superuser?: boolean }>()?.is_superuser === true;

  useEffect(() => {
    if (draft) {
      const value = draft.manager_edited ?? draft.ai_draft ?? "";
      setText(value);
      if (draft.guard_status === "block") {
        setNotice(draft.guard_errors?.join(" · ") ?? "Сообщение не прошло проверку.");
      } else {
        setNotice(null);
      }
    }
  }, [draft]);

  if (!draft) return null;

  const status = draft.status;
  const guardOk = draft.guard_status === "pass";
  const hasPendingApproval = approval?.status === "pending";
  const canSend = status === "draft" && text.trim().length > 0;
  const canApprove = hasPendingApproval && isManager;
  const canReject = hasPendingApproval && isManager;

  return (
    <div className="mt-3 rounded-xl border border-surface-border bg-surface/60 px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          Предложение клиенту
        </span>
        <div className="flex items-center gap-2">
          <span
            className={`badge ${
              guardOk
                ? "bg-emerald-500/15 text-emerald-400"
                : draft.guard_status === "block"
                  ? "bg-rose-500/15 text-rose-400"
                  : "bg-slate-500/15 text-slate-400"
            }`}
          >
            {guardOk ? "Проверено" : draft.guard_status === "block" ? "Заблокировано" : "—"}
          </span>
          <span className="badge bg-slate-500/15 text-slate-300">
            {STATUS_LABEL[status] ?? status}
          </span>
        </div>
      </div>

      {draft.items.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
          {draft.items.map((it) => (
            <span key={it.offer_id}>
              {it.brand} {it.article} — {formatPrice(it.sale_price)}
              {it.delivery_days !== null && it.delivery_days !== undefined
                ? ` · ${it.delivery_days} дн`
                : ""}
            </span>
          ))}
        </div>
      ) : null}

      <textarea
        className="input mt-3 min-h-[120px] w-full resize-y"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={status !== "draft" || busy}
        placeholder="Сообщение клиенту с вариантами…"
      />

      {notice ? <div className="mt-2 text-xs text-rose-400">{notice}</div> : null}

      {status === "sent" && draft.final_message ? (
        <div className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-slate-300">
          Отправлено: {draft.final_message}
        </div>
      ) : null}

      {status === "accepted" ? (
        <div className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-slate-300">
          Клиент подтвердил выбор — можно оформить заказ.
        </div>
      ) : null}

      {order ? (
        <div className="mt-2 rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs text-slate-200">
          <b className="text-white">{order.order_number}</b> · {formatPrice(order.order_total)}{" "}
          {order.currency} · статус{" "}
          <span className="text-white">{order.status}</span>
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canSend ? (
          <>
            <button
              className="btn-primary"
              disabled={busy}
              title={isManager ? "Отправить клиенту без отдельного подтверждения" : undefined}
              onClick={() => (isManager ? onSendNow(text) : onSend(text))}
            >
              {isManager ? "Отправить клиенту" : "Отправить на согласование"}
            </button>
            {isManager ? (
              <button className="btn-ghost" disabled={busy} onClick={() => onSend(text)}>
                Отправить на согласование
              </button>
            ) : null}
          </>
        ) : null}
        {canApprove ? (
          <button
            className="btn-primary"
            disabled={busy}
            onClick={() => onApprove(approval.id)}
          >
            Одобрить и отправить клиенту
          </button>
        ) : null}
        {canReject ? (
          <button
            className="btn-danger"
            disabled={busy}
            onClick={() => onReject(approval.id)}
          >
            Отклонить
          </button>
        ) : null}
        {status === "sent" ? (
          <button className="btn-ghost" disabled={busy} onClick={onAccept}>
            Клиент принял предложение
          </button>
        ) : null}
        {(status === "sent" || status === "accepted") && isManager ? (
          <button className="btn-primary" disabled={busy} onClick={onConvert}>
            Создать заказ
          </button>
        ) : null}
        {hasPendingApproval ? (
          <span className="text-xs text-slate-400">
            Ожидает решения менеджера
            {approval.expires_at ? (
              <>
                {" · "}до {new Date(approval.expires_at).toLocaleString("ru-RU")}
              </>
            ) : null}
          </span>
        ) : null}
      </div>
    </div>
  );
}
