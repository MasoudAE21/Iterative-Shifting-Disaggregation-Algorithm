"""Experiments with synthetic truth are distinct from real-data plausibility."""
from dataclasses import replace
import math
import numpy as np
import pandas as pd
from .config import Config
from .solver import State,solve,initialize,correct_roundoff

def synthetic_experiment(seed=17):
    """Return errors for three allocation methods across four synthetic scenarios.

    Each scenario provides known customer-day truth, aggregated into bills before
    reconstruction. These metrics do not establish accuracy on real local data.
    """
    # One shared generator: scenario order and random-call order affect later draws.
    rng = np.random.default_rng(seed)
    n_days = 90
    n_customers = 24
    weather = np.maximum(18 + 15 * np.sin(np.arange(n_days) / 8) + 5 * np.cos(np.arange(n_days) / 3), 0)
    report = []
    for scenario in [
        'common_noiseless',
        'heterogeneous_high_weather',
        'weak_weather',
        'synchronized_identical_bill_information',
    ]:
        truth = []
        starts = []
        lengths = []
        totals = []
        owners = []
        for customer_index in range(n_customers):
            if scenario == 'common_noiseless':
                daily_truth = (customer_index + 1) / 10 * (1 + weather)
            elif scenario == 'heterogeneous_high_weather':
                daily_truth = np.maximum(
                    0,
                    rng.uniform(1, 5) + rng.uniform(0.2, 2) * weather
                    + rng.normal(0, 2, n_days),
                )
                daily_truth[n_days // 2:] *= rng.uniform(0.4, 1.3)
            elif scenario == 'weak_weather':
                daily_truth = np.maximum(0, rng.uniform(10, 20) + rng.normal(0, 5, n_days))
            else:
                daily_truth = 10 + 8 * np.sin(np.arange(n_days) * 2 * np.pi / 15 + customer_index % 2 * np.pi)
            if customer_index == 0:
                daily_truth = np.zeros(n_days)
            truth.append(daily_truth)
            # Convert known daily values into the bill constraints seen by each method.
            bill_start = 0
            while bill_start < n_days:
                bill_length = min(
                    15 if scenario == 'synchronized_identical_bill_information'
                    else int(rng.integers(7, 23)),
                    n_days - bill_start,
                )
                starts.append(bill_start)
                lengths.append(bill_length)
                totals.append(math.fsum(daily_truth[bill_start:bill_start + bill_length]))
                owners.append(customer_index)
                bill_start += bill_length
        truth = np.array(truth)
        offsets = np.r_[0, np.cumsum(lengths)].astype(np.int64)
        state = State(
            np.array(starts, np.int64),
            np.array(lengths, np.int64),
            np.array(totals, float),
            offsets,
            n_days,
        )
        cfg = Config(mode='paper_reference', feature_preset='paper_section3_v1', checkpoint=False)
        # Exercise reference equations with a custom intercept/weather design.
        design = np.column_stack([np.ones(n_days), weather])
        result = solve(state, design, cfg)
        uniform = initialize(state, cfg)
        weighted = np.empty_like(uniform)
        for bill_index, total in enumerate(totals):
            bill_start = starts[bill_index]
            bill_length = lengths[bill_index]
            bill_weights = 1 + weather[bill_start:bill_start + bill_length]
            weighted[offsets[bill_index]:offsets[bill_index + 1]] = correct_roundoff(
                total * bill_weights / math.fsum(bill_weights), total, cfg,
            )
        for method, allocations in [
            ('isd_reference_equations', result.allocations),
            ('uniform', uniform),
            ('weather_weighted', weighted),
        ]:
            estimate = np.zeros_like(truth)
            for bill_index, customer_index in enumerate(owners):
                estimate[
                    customer_index, starts[bill_index]:starts[bill_index] + lengths[bill_index]
                ] = allocations[offsets[bill_index]:offsets[bill_index + 1]]
            true_daily_total = truth.sum(axis=0)
            estimated_daily_total = estimate.sum(axis=0)
            aggregate_error = estimated_daily_total - true_daily_total
            true_total_consumption = true_daily_total.sum()
            positive_customers = truth.sum(axis=1) > 0
            # Exclude zero-total customers only from metrics requiring division by truth.
            customer_wape = (
                np.sum(np.abs(estimate - truth), axis=1)[positive_customers]
                / truth.sum(axis=1)[positive_customers]
            )
            report.append({
                'scenario': scenario,
                'method': method,
                'aggregate_mae': float(np.mean(np.abs(aggregate_error))),
                'aggregate_rmse': float(np.sqrt(np.mean(aggregate_error ** 2))),
                'aggregate_wape': (
                    float(np.abs(aggregate_error).sum() / true_total_consumption)
                    if true_total_consumption else None
                ),
                'signed_bias': float(np.mean(aggregate_error)),
                # Value error on the true population peak day, not peak-magnitude difference.
                'peak_day_absolute_error': float(abs(
                    estimated_daily_total[np.argmax(true_daily_total)] - true_daily_total.max()
                )),
                'peak_day_timing_error_days': int(
                    np.argmax(estimated_daily_total) - np.argmax(true_daily_total)
                ),
                'customer_mean_mae': float(np.mean(np.abs(estimate - truth))),
                'customer_median_wape_positive_only': float(np.median(customer_wape)),
                'customer_p90_wape_positive_only': float(np.percentile(customer_wape, 90)),
                'zero_only_customers': int(np.sum(~positive_customers)),
                'truth_source': 'Known synthetic daily values; not evidence about local daily accuracy',
            })
    return pd.DataFrame(report)
