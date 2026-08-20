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

export type PackDependency = {
  name: string;
  version_req: string;
};

export type Pack = {
  id: string;
  name: string;
  version: string;
  display_name: string;
  description: string;
  base_url: string;
  required_core_version: string;
  state: string;
  is_active: boolean;
  agents: { type: string; display_name?: string }[];
  permissions: string[];
  workflows: { name: string; version?: string }[];
  tools: string[];
  developer: string;
  homepage: string;
  license: string;
  dependencies: PackDependency[];
  checksum: string;
  signature: string;
  last_healthcheck_at: string | null;
  last_health_ok: boolean | null;
  config: Record<string, unknown>;
};

export type PackList = {
  packs: Pack[];
};

export type PlatformOverview = {
  companies: number;
  agents: number;
  agents_active: number;
  tasks: number;
  tasks_completed: number;
  tasks_failed: number;
  packs: number;
  packs_active: number;
  workflows: number;
  tools: number;
  approvals_pending: number;
};

export type PlatformWorkflowNode = {
  id: string;
  type: string;
  [key: string]: unknown;
};

export type PlatformWorkflow = {
  pack: string;
  name: string;
  version: string;
  start: string;
  nodes: PlatformWorkflowNode[];
};

export type PlatformWorkflowList = {
  workflows: PlatformWorkflow[];
  errors: { pack: string; error: string }[];
};

export type PlatformTool = {
  name: string;
  source: string;
  pack: string | null;
};

export type PlatformToolList = {
  tools: PlatformTool[];
};

export type PlatformApproval = {
  id: string;
  company_id: string;
  agent_id: string | null;
  task_id: string | null;
  action_type: string;
  target_type: string | null;
  target_id: string | null;
  risk_level: string;
  input_data: Record<string, unknown> | null;
  created_at: string;
};

export type PlatformApprovalList = {
  approvals: PlatformApproval[];
};

export type UsageBucket = {
  [key: string]: unknown;
};

export type UsageSummary = {
  days: number;
  totals: {
    tasks_total: number;
    tasks_completed: number;
    tasks_failed: number;
    approvals_pending: number;
    approvals_decided: number;
    llm_calls: number;
    llm_tokens: number;
    llm_cost_rub: number;
    agent_executions: number;
    tool_calls: number;
    workflow_runs: number;
  };
  by_tenant: UsageBucket[];
  by_pack: UsageBucket[];
  by_workflow: UsageBucket[];
  by_agent: UsageBucket[];
  storage_rows: Record<string, number>;
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
  must_change_password: boolean;
  role?: string;
  created_at: string;
};

export type EmergencyStatus = {
  engaged: boolean;
  reason: string | null;
  engaged_at: string | null;
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
  request_id: string | null;
  user_agent: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type AuditList = {
  total: number;
  items: AuditEvent[];
  next_cursor: string | null;
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

export type GarageVehicle = {
  id: string;
  vin: string;
  brand: string;
  model: string;
  year: number | null;
  engine: string;
  body: string;
  registration_number: string;
};

export type GaragePurchase = {
  order_id: string;
  order_number: string;
  status: string;
  created_at: string;
  part_name: string;
  article: string;
  brand: string;
  total_price: string | null;
  quantity: number | null;
};

export type CustomerGarage = {
  customer_id: string;
  memory: {
    segment: string;
    avg_check: number | null;
    preferences: Record<string, unknown>;
    updated_at?: string | null;
    avg_check_updated_at?: string | null;
  };
  vehicles: {
    vehicle: GarageVehicle;
    history: GaragePurchase[];
  }[];
};

export type CustomerMemory = {
  customer_id: string;
  segment: string;
  avg_check: number | null;
  preferences: Record<string, unknown>;
  updated_at?: string | null;
  avg_check_updated_at?: string | null;
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
  is_experimental: boolean;
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
  rank: number | null;
  rank_score: string | null;
  rank_reasons: string[] | null;
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
  offer_id?: string;
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
  auto_sent?: boolean;
  auto_reasons?: string[] | null;
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
  tracking_status: string;
  currency: string;
  order_total: string | null;
  items: QuoteItem[];
  created_by_user_id: string | null;
  confirmed_at: string | null;
  created_at: string;
};

export type SupplierTrackingSupplier = {
  supplier_id: string;
  supplier_name: string;
  external_order_id: string | null;
  supplier_status: string | null;
};

export type SupplierTracking = {
  order_id: string;
  order_number: string;
  order_status: string;
  tracking_status: string;
  suppliers: SupplierTrackingSupplier[];
  notification: Record<string, unknown> | null;
};

export type SupplierPurchase = {
  approval_id: string;
  order_id: string | null;
  order_number: string | null;
  supplier_id: string | null;
  supplier_name: string;
  action_type: string;
  status: string;
  risk_level: string;
  external_order_id: string | null;
  supplier_status: string | null;
  order_status: string | null;
  tracking_status: string | null;
  items: Record<string, unknown>[];
  order_total: string | null;
  created_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  expires_at: string | null;
};

export type SupplierHandOverResult = {
  order_id: string;
  order_number: string;
  tracking_status: string;
  already_handed_over: boolean;
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

export type PackMetricsEntry = {
  namespace: string;
  status: "ok" | "unavailable";
  metrics?: {
    suppliers?: { attempts_total: number; success_rate: number | null };
    orders?: number;
    revenue?: number;
    quotes_sent?: number;
    part_requests_total?: number;
    appointments?: number;
    services?: number;
  } | null;
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
  p95_response_seconds?: number | null;
  pipeline: PipelineStageStats[];
  suppliers: SupplierStats;
  llm: LlmStats;
  task_timeouts: number;
  assist?: AssistStats | null;
  sprint39?: Sprint39Report | null;
  packs?: PackMetricsEntry[];
};

export type Sprint39Report = {
  target_requests: number;
  real_requests: number;
  remaining_to_target: number;
  intake_accuracy: number | null;
  search_success: number | null;
  correct_fitment: number | null;
  quotes_generated: number | null;
  quote_guard_pass: number | null;
  manager_unchanged_send: number | null;
  manager_edited: number | null;
  manager_rejected: number | null;
  manager_sends_total: number;
  controlled_auto_eligible: number | null;
  controlled_auto_sent: number | null;
  auto_send_error_rate: number | null;
  avg_response_seconds: number | null;
  p95_response_seconds: number | null;
  quote_to_accepted: number | null;
  accepted_to_order: number | null;
  revenue: string;
  gross_profit: string;
  llm_cost_per_request: string;
  infra_cost_per_request: string;
  total_cost_per_request: string;
  human_takeover: number | null;
  full_automation: number | null;
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

export type AttentionCounts = {
  client_waiting_reply: number;
  approval_pending: number;
  ai_unsure: number;
  supplier_error: number;
};

export type TodayCounts = {
  requests: number;
  selections: number;
  quotes: number;
  sent: number;
  orders: number;
};

export type QueueItem = {
  type: string;
  action: string;
  title: string;
  customer: string;
  part: string;
  vehicle: string;
  conversation_id: string | null;
  quote_id?: string | null;
  approval_id?: string | null;
  part_request_id?: string | null;
  created_at: string;
};

export type ShadowStats = {
  total: number;
  completed: number;
  pending: number;
  limit: number;
  vehicle_match_pct: number | null;
  part_match_pct: number | null;
  oem_match_pct: number | null;
  avg_time_seconds: number | null;
  shadow_mode?: boolean;
};

export type ShadowComparison = {
  id: string;
  part_request_id: string;
  conversation_id: string;
  status: string;
  ai: {
    vehicle: string;
    part: string;
    article: string;
    offer_ids: string[];
    price: string | null;
    answer: string;
  };
  manager: {
    vehicle: string;
    part: string;
    article: string;
    offer_ids: string[];
    price: string | null;
    reply: string;
  };
  result: {
    vehicle_match: boolean | null;
    part_match: boolean | null;
    oem_match: boolean | null;
    offer_overlap: number;
    price_delta: string | null;
    time_seconds: number | null;
  };
  evaluated_at: string | null;
  created_at: string;
};

export type ShadowList = {
  items: ShadowComparison[];
  stats: ShadowStats;
  shadow_mode: boolean;
};

export type ManagerDashboard = {
  attention: AttentionCounts;
  today: TodayCounts;
  queue: QueueItem[];
  shadow: ShadowStats;
  assist: AssistStats;
};

export type AssistStats = {
  sends_total: number;
  sends_unchanged: number;
  sends_edited: number;
  sends_rejected: number;
  manager_edit_rate: number | null;
  auto_sends?: number;
};

export type FitmentSource = {
  source: string;
  weight: number;
  score: number;
  detail: string;
};

export type FitmentExplain = {
  level: "high" | "medium" | "low";
  confidence: number;
  vehicle_dependent: boolean;
  verdict: string;
  sources: FitmentSource[];
  vin: {
    vin: string;
    valid: boolean;
    brand: string;
    year: number | null;
    reason: string;
  };
  computed_at: string;
  engine_version: string;
  checks: string[];
  warnings: string[];
};

export type VerifyRequest = {
  article: string;
  brand: string;
  result: "confirmed" | "rejected";
};

export type SupplierReliability = {
  supplier_id: string;
  supplier_name: string;
  rating: number;
  rating_source: string;
  rating_version: string;
  computed_at: string;

  orders_total: number;
  confirmed: number;
  cancelled: number;
  confirmation_rate: number | null;
  cancellation_rate: number | null;

  fulfillments_total: number;
  fulfillments_recorded: number;
  on_time_delivery: number | null;
  price_change_rate: number | null;
  under_delivery_rate: number | null;

  returns_total: number;
  return_rate: number | null;

  attempts_total: number;
  attempts_failed: number;
  api_availability: number | null;
  api_avg_latency_ms: number | null;
  api_p95_latency_ms: number | null;

  reliability_score: number;
  api_score: number;
};

export type SupplierFulfillment = {
  id: string;
  company_id: string;
  supplier_id: string;
  order_id: string | null;
  offer_id: string | null;
  article: string;
  brand: string;
  promised_purchase_price: string | null;
  promised_delivery_days: number | null;
  quantity_ordered: number | null;
  actual_purchase_price: string | null;
  actual_delivery_days: number | null;
  quantity_delivered: number | null;
  status: string;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
};
