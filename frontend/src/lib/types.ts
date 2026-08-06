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
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  events?: TaskEvent[];
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

export type ToolInfo = {
  name: string;
  description: string;
  version: string;
  input_schema: Record<string, unknown>;
};
