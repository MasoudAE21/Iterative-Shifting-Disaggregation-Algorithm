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
    sample_seed: str = 'isd_pilot_v1:'
    # Select a shared population peak day or each customer's own peak day.
    peak_mode: str = 'population'
    row_group_size: int = 100000
    ingestion_chunk_size: int = 100000
    memmap_threshold_mb: int = 256
    checkpoint: bool = True
    resume: bool = False
    # Legacy library default; the IDE entry point opts into weather-bounded exclusion.
    bill_boundary_policy: str = 'keep'
    bill_window: str = 'weather'

    def validate(self):
        if self.bill_boundary_policy not in ('keep', 'exclude', 'prorate'):
            raise ValueError('Unknown bill boundary policy')
        if self.bill_window not in ('target', 'weather'):
            raise ValueError('Unknown bill window')
        if self.production and self.bill_boundary_policy == 'prorate':
            raise ValueError('Prorated bill totals are provisional estimates')
        if self.peak_mode not in ('population', 'individual'):
            raise ValueError('Unknown peak mode')
        if self.feature_preset not in (
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
            or self.coverage_policy != 'balanced_cohort_uniform_elsewhere_v1'
            or self.residual_tolerance_policy != '64eps_length_max_scale_v1'
        ):
            raise ValueError('Unregistered policy requires a separate adaptation')
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
