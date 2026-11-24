export interface DemoYear {
  year: number;
  role: string;
  p_relief_by_week: { week: number; p_relief: number | null }[];
}

export interface Band {
  p10?: number | null;
  p50?: number | null;
  p90?: number | null;
}

export interface WeekRow {
  week_index: number;
  cumulative_rainfall_mm?: number | null;
  rain_pct_of_normal?: number | null;
  p_relief?: number | null;
  rule_score?: number | null;
  projected_total_mm?: Band | null;
  explanations?: { en?: string; fil?: string };
}

export interface ScheduleRow {
  month: number;
  due: string;
  payment_cents: number;
  note?: string;
}

export interface ScheduleSummary {
  baseline_total_paid_cents?: number;
  relief_total_paid_cents?: number;
  extra_cost_cents?: number;
  payment_saved_first_relief_month_cents?: number;
  baseline_months?: number;
  relief_months?: number;
  first_relief_month?: number | null;
  baseline_end?: string;
  relief_end?: string;
}

export interface SchedulePreview {
  before: ScheduleRow[];
  after: ScheduleRow[];
  summary: ScheduleSummary;
}

export interface DemoRun {
  year: number;
  limitations?: string[];
  weekly: WeekRow[];
  rainfall_line?: {
    trigger_rainfall_mm?: number;
    observed_rainfall_mm?: number | null;
    fired?: boolean;
  };
  loan?: {
    id?: number;
    create_tx_hash?: string;
    principal_cents?: number;
    annual_rate_bps?: number;
    term_months?: number;
    trigger_rainfall_tenths_mm?: number;
    max_reduction_bps?: number;
    max_deferral_months?: number;
  };
  oracle?: {
    relief_applied?: boolean;
    tx_hash?: string | null;
    evidence_hash?: string | null;
    reason?: string;
    season_total_mm?: number;
    trigger_mm?: number;
    relief_kind?: string;
    relief_value?: number;
  };
  schedule_before?: ScheduleRow[];
  schedule_after?: ScheduleRow[];
  summary?: ScheduleSummary;
  comparison_note?: string;
  example_relief?: { kind?: string; value?: number; start_month?: number; window_months?: number };
}

export interface RiskBody {
  season_year?: number;
  season_status?: string;
  p_relief?: number | null;
  rule_score?: number | null;
  projected_total_mm?: Band | null;
  explanations?: { en?: string; fil?: string; source?: string };
  trigger?: { fired?: boolean | null; trigger_rainfall_mm?: number };
  limitations?: string[];
}

export interface RegionBody {
  name?: string;
  crop?: string;
  trigger?: { proposed_trigger_rainfall_mm?: number };
  limitations?: string[];
}

export interface BacktestRow {
  year: number;
  season_total_mm?: number | null;
  relief_fired?: boolean;
  p_relief?: Record<string, number | null>;
  first_week_p_relief_at_least_0_5?: number | null;
  false_alarm?: boolean;
  harvest?: { yield_t_per_ha?: number | null; vs_trend_pct?: number | null } | null;
}

export interface BacktestBody {
  method?: string;
  payment_line_mm?: number;
  n_seasons?: number;
  n_positive_seasons?: number;
  small_sample_note?: string;
  beats_rule_baseline?: boolean;
  rows?: BacktestRow[];
  harvest?: { source?: string; province?: string; fetched_at?: string; trend_t_per_ha_per_year?: number | null } | null;
  trend?: {
    linear_trend_mm_per_year?: number;
    linear_trend_p_value?: number;
    trend_note?: string;
    season_totals_mm?: { year: number; season_total_mm: number }[];
    rolling_10_year_mean_mm?: { end_year: number; mean_mm: number }[];
    below_the_line_by_window?: { window: string; seasons: number; below_the_line: number; note: string }[];
  };
  dry_spell_limitation?: { definition?: string };
  newer_years?: {
    year: number;
    season_total_mm?: number;
    relief_fired?: boolean;
    max_p_relief?: number;
    first_week_p_relief_at_least_0_5?: number | null;
  }[];
  candidates?: Record<
    string,
    {
      mean_brier_without_week_21?: number;
      mean_brier_with_week_21?: number;
      by_week?: Record<string, { brier?: number; brier_skill?: number | null }>;
    }
  >;
  limitations?: string[];
  metadata?: {
    headline_metric?: string;
    brier_skill_definition?: string;
    climatology?: string;
    climatology_brier_by_week?: Record<string, number>;
    mean_brier_without_week_21?: Record<string, number>;
    mean_brier_with_week_21?: Record<string, number>;
    brier_skill_by_week?: Record<string, Record<string, number | null>>;
    selection_bias?: string;
  };
}

export interface EvidenceCheck {
  claimed_hash?: string;
  recomputed_hash?: string;
  matches?: boolean;
}
