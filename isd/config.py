import math
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass(frozen=True)
class Config:
    """Run settings shared by preparation, solving and export.

    Construction does not validate values; call validate() before using them.
    """

    # Mode selects the scientific formulation; engine selects its implementation.
    mode: str = 'provisional_cohort_isd'
    engine: str = 'scaled'
    alpha: float = 0.05
    n_lr_models: int = 10
    n_disagg_cycles: int = 10
    # The target is half-open; source bill endpoints remain inclusive.
    target_start: str = '2025-01-20'
    target_end_exclusive: str = '2025-03-21'
    timezone: str = 'Asia/Tehran'
    feature_preset: str = 'winter_hdd65_v1'
    endpoint_convention: str = 'inclusive'
    endpoint_confirmed: bool = False
    calendar_origin_confirmed: bool = False
    day_basis_confirmed: bool = False
    target_year_confirmed: bool = False
    target_jalali_year_candidate: int = 1403
    physical_zero_confirmed: bool = False
    export_unmodified_confirmed: bool = False
    consumption_unit: str = 'source_units_unknown'
    provider_variable_definition: str = 'instant'
    weather_adapter: str = 'point_linear_integral_v1'
    allow_daily_timezone_mismatch: bool = False
    ordering_version: str = 'customer_start_end_bill_id_v1'
    coverage_policy: str = 'balanced_cohort_uniform_elsewhere_v1'
    zero_residual_policy: str = 'keep_current'
    residual_tolerance_policy: str = '64eps_length_max_scale_v1'
    reconciliation_atol: float = 1e-8
    reconciliation_rtol: float = 1e-10
    regression_rcond: float | None = None
    exposure_scaled: bool = True
    production: bool = False
    max_customers: int | None = 1000
    sample_scope: str = 'universe'
    consumption_types: list[str] | None = None
    sample_seed: str = 'isd_pilot_v1:'
    # Select a shared population peak day or each customer's own peak day.
    peak_mode: str = 'population'
    # Optional monthly CSV copies; the compact Parquet daily output is always kept.
    export_customer_daily_csv: bool = False
    row_group_size: int = 100000
    ingestion_chunk_size: int = 100000
    memmap_threshold_mb: int = 256
    checkpoint: bool = True
    resume: bool = False
    # Legacy library default; the IDE entry point opts into weather-bounded exclusion.
    bill_boundary_policy: str = 'keep'
    bill_window: str = 'weather'
    simulation_start: str = '2024-11-01'
    simulation_end_exclusive: str = '2025-04-01'
    max_bill_days: int | None = None
    bill_duration_scope: str = 'all'
    bill_date_format: str = '%Y-%m-%d'
    tbs_fourier_harmonics: int = 3
    tbs_fourier_period_days: float = 365.2425
    tbs_path: str | None = None
    initialization: str = 'uniform'
    redistribution_floor: float = 0.0
    individual_reference_strength: float = 0.0
    customer_summer_floor: bool = False
    summer_floor_fraction: float = 0.95
    summer_min_covered_days: int = 30
    summer_fallback_fraction: float = 0.10
    divide_consumption_by_unit_count: bool = False

    def validate(self):
        if self.consumption_types is not None and (
            not isinstance(self.consumption_types, list) or not self.consumption_types
            or any(not isinstance(v, str) or not v.isdigit() for v in self.consumption_types)
            or len(set(self.consumption_types)) != len(self.consumption_types)
        ):
            raise ValueError('consumption_types must be null or a nonempty list of unique numeric strings')
        if self.initialization not in ('uniform', 'seasonal_reference'):
            raise ValueError('Unknown initialization')
        for name in ('customer_summer_floor', 'divide_consumption_by_unit_count'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f'{name} must be boolean')
        if (isinstance(self.summer_min_covered_days, bool) or
                not isinstance(self.summer_min_covered_days, int) or self.summer_min_covered_days < 1):
            raise ValueError('summer_min_covered_days must be a positive integer')
        for value in (self.redistribution_floor, self.individual_reference_strength,
                      self.summer_floor_fraction, self.summer_fallback_fraction):
            if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Reserve and correction must be finite fractions')
        if self.mode == 'paper_reference' and (self.initialization != 'uniform' or
                self.redistribution_floor or self.individual_reference_strength or self.customer_summer_floor):
            raise ValueError('Experimental corrections require cohort mode')
        if self.feature_preset in ("tbs_fourier_v1", "town_tbs_fourier_v1"):
            if not self.tbs_path:
                raise ValueError("TBS Fourier features require tbs_path")
            if isinstance(self.tbs_fourier_harmonics, bool) or not isinstance(self.tbs_fourier_harmonics, int) or self.tbs_fourier_harmonics < 1:
                raise ValueError("Fourier harmonics must be a positive integer")
            if not math.isfinite(self.tbs_fourier_period_days) or self.tbs_fourier_period_days <= 0:
                raise ValueError("Fourier period must be finite and positive")
        if not isinstance(self.export_customer_daily_csv, bool):
            raise ValueError('export_customer_daily_csv must be boolean')
        if self.bill_duration_scope not in ('all', 'boundary'):
            raise ValueError('Unknown bill duration scope')
        if self.bill_date_format not in ('%Y-%m-%d', '%m/%d/%Y'):
            raise ValueError('Unsupported bill date format')
        if self.bill_boundary_policy not in ('keep', 'exclude', 'prorate', 'clip_preserve_total', 'monthly_weighted'):
            raise ValueError('Unknown bill boundary policy')
        if self.bill_window not in ('target', 'weather', 'simulation'):
            raise ValueError('Unknown bill window')
        if self.bill_boundary_policy == 'monthly_weighted' and self.bill_window != 'target':
            raise ValueError('monthly_weighted requires bill_window=target')
        if self.production and self.bill_boundary_policy in ('prorate', 'monthly_weighted'):
            raise ValueError('Prorated bill totals are provisional estimates')
        if self.max_bill_days is not None and (isinstance(self.max_bill_days, bool) or not isinstance(self.max_bill_days, int) or self.max_bill_days < 1):
            raise ValueError('max_bill_days must be a positive integer')
        if self.peak_mode not in ('population', 'individual'):
            raise ValueError('Unknown peak mode')
        if self.feature_preset not in (
            'tbs_fourier_v1',
            'town_tbs_fourier_v1',
            'town_custom_v1',
            'paper_section3_v1',
            'winter_hdd65_v1',
            'winter_hdd65_hddw65_v1',
            'intercept_only_v1',
            'daily_apparent_hdd65_v1',
        ):
            raise ValueError('Unregistered feature preset')
        for value in (self.reconciliation_atol, self.reconciliation_rtol):
            if not math.isfinite(value) or value < 0:
                raise ValueError('Finite nonnegative tolerances required')
        if self.mode not in ('paper_reference', 'provisional_cohort_isd'):
            raise ValueError('Unknown mode')
        if self.engine not in ('reference', 'scaled'):
            raise ValueError('Unknown engine')
        if not 0 <= self.alpha <= 1:
            raise ValueError('alpha outside [0,1]')
        for count in (
            self.n_lr_models,
            self.n_disagg_cycles,
            self.row_group_size,
            self.ingestion_chunk_size,
        ):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError('Positive integer counts required')
        if (
            self.ordering_version != 'customer_start_end_bill_id_v1'
            or self.coverage_policy not in ('balanced_cohort_uniform_elsewhere_v1', 'observed_support_isd_v1')
            or self.residual_tolerance_policy != '64eps_length_max_scale_v1'
        ):
            raise ValueError('Unregistered policy requires a separate adaptation')
        if self.coverage_policy == 'observed_support_isd_v1' and not self.exposure_scaled:
            raise ValueError('Observed-support modeling requires exposure scaling')
        if self.regression_rcond is not None and not 0 <= self.regression_rcond < 1:
            raise ValueError('Invalid rcond')
        if self.endpoint_convention != 'inclusive':
            raise ValueError('Other endpoints require a separately audited adapter')
        if self.max_customers is not None and (
            not isinstance(self.max_customers, int) or self.max_customers < 1
        ):
            raise ValueError('Invalid customer limit')
        if self.sample_scope not in ('universe', 'cohort'):
            raise ValueError('Unknown sampling scope')
        if self.zero_residual_policy != 'keep_current':
            raise ValueError('Unsupported zero residual policy')
        if self.production and (
            not all([
                self.target_year_confirmed,
                self.endpoint_confirmed,
                self.calendar_origin_confirmed,
                self.day_basis_confirmed,
                self.export_unmodified_confirmed,
            ])
            or self.consumption_unit == 'source_units_unknown'
        ):
            raise ValueError('Production semantic gates unresolved; use provisional exploratory mode')
        if self.mode == 'paper_reference' and self.feature_preset != 'paper_section3_v1':
            raise ValueError('Reference mode requires the Section 3 example features')
        return self

    def as_dict(self):
        return asdict(self)
