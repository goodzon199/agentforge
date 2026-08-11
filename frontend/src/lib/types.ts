export type Company = {
  id: string;
  name: string;
  slug: string;
  description: string;
  is_active: boolean;
  agent_quota: number;
  agents_count: number;
  tasks_count: number;
  created_at: string;
};

export type Agent = {
  id: string;
  company_id: string;
  name: string;
  role: string;
  slug: string;
  goal: string;
  description: string;
  instructions: string;
  type: string;
  model: string;
  temperature: number;
  status: string;
  is_active: boolean;
  tasks_total: number;
  tasks_completed: number;
  tasks_failed: number;
  avg_success_rate: number;
  total_llm_calls: number;
  tools: { tool_name: string; enabled: boolean }[];
  created_at: string;
};

export type Task = {
  id: string;
  company_id: string;
  agent_id: string | null;
  title: string;
  objective: string;
  status: string;
  priority: string;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
  error: string | null;
  routing_decision: Record<string, unknown> | null;
  retries: number;
  replayed_from_task_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  events?: TaskEvent[];
};

export type DeadTask = {
  id: string;
  task_id: string;
  company_id: string;
  agent_id: string | null;
  objective: string;
  payload: Record<string, unknown>;
  exception_kind: string;
  error: string | null;
  attempts: number;
  dead_at: string;
  replayed_task_id: string | null;
  created_at: string;
};

export type TaskEvent = {
  id: string;
  task_id: string;
  agent_id: string | null;
  source: string;
  level: string;
  message: string;
  meta: Record<string, unknown>;
  created_at: string;
};

export type DashboardStats = {
  companies: number;
  agents: number;
  tasks: number;
  tasks_completed: number;
  tasks_failed: number;
  agents_active: number;
  logs_total: number;
};

export type TraceSummary = {
  id: string;
  company_id: string | null;
  conversation_id: string | null;
  status: string;
  started_at: string;
  completed_at: string | null;
  source: string;
  created_at: string;
  span_count: number;
  error_kinds: string[];
};

export type SpanNode = {
  span: {
    id: string;
    trace_id: string;
    parent_span_id: string | null;
    span_type: string;
    name: string;
    agent_id: string | null;
    task_id: string | null;
    supplier_id: string | null;
    order_id: string | null;
    status: string;
    started_at: string;
    finished_at: string | null;
    duration_ms: number | null;
    meta: Record<string, unknown>;
    error_kind: string | null;
  };
  children: SpanNode[];
};

export type TraceTree = {
  trace: TraceSummary;
  root: SpanNode | null;
};

export type ToolInfo = {
  name: string;
  description: string;
  version: string;
  input_schema: Record<string, unknown>;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  company_id: string | null;
  created_at: string;
};

export type AuditEvent = {
  id: string;
  company_id: string | null;
  user_id: string | null;
  actor_type: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  ip_address: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type AuditList = {
  total: number;
  items: AuditEvent[];
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

export type Customer = {
  id: string;
  company_id: string;
  name: string;
  phone: string;
  email: string;
  source: string;
  external_id: string;
  created_at: string;
};

export type ConversationMode = "ai_active" | "human_active" | "paused" | "closed";

export type Conversation = {
  id: string;
  company_id: string;
  customer_id: string;
  channel: string;
  status: string;
  mode: ConversationMode;
  assigned_user_id: string | null;
  created_at: string;
  updated_at: string;
  customer_name: string;
};

export type ConversationMessage = {
  id: string;
  conversation_id: string;
  sender_type: string;
  sender_id: string | null;
  content: string;
  structured_data: Record<string, unknown>;
  created_at: string;
  task_id?: string | null;
};

export type ConversationDetail = Conversation & {
  messages: ConversationMessage[];
};

export type MessageSent = {
  message: ConversationMessage;
  task_id: string | null;
};

export type Vehicle = {
  id: string;
  company_id: string;
  customer_id: string;
  vin: string;
  brand: string;
  model: string;
  year: number | null;
  engine: string;
  body: string;
  registration_number: string;
  created_at: string;
  updated_at: string;
};

export type PartRequest = {
  id: string;
  company_id: string;
  conversation_id: string;
  customer_id: string;
  vehicle_id: string | null;
  source_message_id: string | null;
  intent: string;
  part_name: string;
  article: string;
  quantity: number;
  status: string;
  missing_fields: string[];
  structured_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  vehicle: Vehicle | null;
  customer_name: string;
};

export type Supplier = {
  id: string;
  company_id: string;
  name: string;
  slug: string;
  adapter_type: string;
  is_active: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SupplierOffer = {
  id: string;
  part_request_id: string;
  search_run_id: string;
  supplier_id: string;
  supplier_name: string;
  brand: string;
  article: string;
  part_name: string;
  purchase_price: string | null;
  quantity: number | null;
  delivery_days: number | null;
  customer_price: string | null;
  total_price: string | null;
  margin_percent: string | null;
  created_at: string;
};

export type SupplierAttempt = {
  id: string;
  supplier_id: string;
  supplier_name: string;
  status: string;
  offers_found: number;
  error: string;
  latency_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
};

export type SupplierSearchRun = {
  id: string;
  part_request_id: string;
  status: string;
  offers_found: number;
  suppliers_succeeded: number;
  suppliers_failed: number;
  error: string;
  structured_data: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  attempts: SupplierAttempt[];
};

export type PartQuote = {
  status: string;
  part_request_id: string;
  run_id: string | null;
  quote_id: string | null;
  triggered_by: string;
  margin_percent: number | null;
  currency: string;
  offers_total: number;
  offers_priced: number;
  quantity: number;
  best_offer_id: string | null;
  best_brand: string;
  best_article: string;
  best_part_name: string;
  best_unit_price: string | null;
  best_total_price: string | null;
  priced_at: string | null;
};

export type QuoteItem = {
  offer_id: string;
  brand: string;
  article: string;
  part_name: string;
  sale_price: string | null;
  total_price: string | null;
  delivery_days: number | null;
  quantity_available: number | null;
  margin_percent: string | null;
};

export type SalesDraft = {
  quote_id: string;
  part_request_id: string;
  conversation_id: string;
  status: string;
  currency: string;
  quote_total: string | null;
  best_offer_id: string | null;
  items: QuoteItem[];
  ai_draft: string | null;
  manager_edited: string | null;
  final_message: string | null;
  guard_status: string;
  guard_errors: string[] | null;
  sent_at: string | null;
  created_at: string | null;
};

export type Approval = {
  id: string;
  company_id: string;
  task_id: string | null;
  conversation_id: string | null;
  quote_id: string | null;
  action_id: string | null;
  action_type: string;
  status: string;
  payload: Record<string, unknown> | null;
  risk_level: string;
  requested_by_agent_id: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  rejected_by_user_id: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  expires_at: string | null;
};

export type QuoteSendResult = {
  approval_id: string | null;
  status: string;
  message_sent: boolean;
  already_executed: boolean;
  quote_id: string | null;
};

export type Order = {
  id: string;
  company_id: string;
  conversation_id: string;
  customer_id: string;
  part_request_id: string;
  quote_id: string | null;
  order_number: string;
  status: string;
  currency: string;
  order_total: string | null;
  items: QuoteItem[];
  created_by_user_id: string | null;
  confirmed_at: string | null;
  created_at: string;
};

export type QuoteAcceptResult = {
  quote_id: string;
  status: string;
  already_accepted: boolean;
};

export type OrderCreateResult = {
  order_id: string | null;
  order_number: string | null;
  quote_id: string;
  status: string;
  already_converted: boolean;
};

export type PipelineStageStats = {
  objective: string;
  count: number;
  failed: number;
  avg_seconds: number | null;
  p95_seconds: number | null;
  sla_seconds: number;
  on_sla_pct: number | null;
};

export type SupplierStats = {
  attempts_total: number;
  attempts_failed: number;
  failure_rate: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
};

export type LlmStats = {
  calls: number;
  failures: number;
  failure_rate: number;
  available: boolean;
};

export type PilotAnalytics = {
  period_days: number;
  requests_total: number;
  conversations_total: number;
  ai_handled: number;
  handed_to_manager: number;
  takeover_rate: number;
  part_requests_total: number;
  quotes_sent: number;
  quotes_accepted: number;
  orders_total: number;
  revenue: string;
  gross_profit: string;
  avg_response_seconds: number | null;
  pipeline: PipelineStageStats[];
  suppliers: SupplierStats;
  llm: LlmStats;
  task_timeouts: number;
};

export type FeedbackRates = {
  feedback_total: number;
  acceptance: number;
  edit: number;
  rejection: number;
  hallucination: number;
  acceptance_rate: number | null;
  edit_rate: number | null;
  rejection_rate: number | null;
  hallucination_rate: number | null;
};

export type AgentQuality = {
  agent_id: string;
  name: string;
  slug: string;
  role: string;
  tasks_total: number;
  tasks_completed: number;
  tasks_failed: number;
  success_rate: number | null;
  avg_response_seconds: number | null;
  feedback: FeedbackRates;
  human_takeover: number | null;
  llm_calls: number;
  total_llm_cost: number;
  cost_per_task: number | null;
};

export type PromptVersionQuality = FeedbackRates & {
  agent_kind: string;
  prompt_version: string;
};

export type AgentQualityReport = {
  days: number;
  agents: AgentQuality[];
  by_prompt_version: PromptVersionQuality[];
};

export type PromptVersion = {
  id: string;
  company_id: string | null;
  agent_kind: string;
  version: string;
  name: string;
  description: string | null;
  content: string;
  is_active: boolean;
};

export type CompanyPolicies = {
  company_id: string;
  pricing: Record<string, unknown>;
  supplier: Record<string, unknown>;
  approval: Record<string, unknown>;
  sales: Record<string, unknown>;
  security: Record<string, unknown>;
  defaults: Record<string, Record<string, unknown>>;
};
