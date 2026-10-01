# Issue #21 numerical reproduction validation

Starting main SHA: `11163d0ec058f838794841aa915832e36e4dfc0f` (includes PR #20).
The working branch started at this SHA with no tracked changes. The unrelated
untracked `ltspice-mcp.toml` was preserved and excluded from the change.

## Baseline control

Windows build 26200, AMD Ryzen 7 9700X, Python 3.11.0, unchanged
`requirements-retrieval.lock.txt`, NumPy 1.26.4, OpenBLAS 0.3.23.dev. This host's
NumPy runtime reports the AVX2/FMA3 and AVX512 extensions required by the tested
kernels. Fresh Python processes selected each kernel with
`OPENBLAS_CORETYPE`; `OPENBLAS_NUM_THREADS=4` was held constant. No production
code, ranking configuration or benchmark evidence was changed for the baseline.

| Fast gate | Cooperlake | Zen |
| --- | --- | --- |
| Unchanged main | PASS (exit 0) | FAIL (exit 1) |
| Scoped numerical comparison | PASS (exit 0) | PASS (exit 0) |

The baseline ran `python scripts/ci_checks.py fast` under both kernels: 69
ordinary tests, exactly three expected model skips, five research tests without
skips, and both schema/CLI comparisons. Zen had exactly one failure,
`RoleEvaluationReproductionTests.test_committed_metrics_and_rankings_reproduce_without_model`.
The skip audit and schema comparisons passed on both kernels.

Recursive comparison of the regenerated in-memory JSON against the committed
reference found 76 Zen differences, all confined to per-query
`intra_list_similarity` and `mean_intra_list_similarity`. The maximum absolute
error was `1.1102230246251565e-16`. Cooperlake had zero differences. All keys,
list lengths, non-diagnostic metrics and the complete ranking JSON were exactly
equal on both kernels. The first Zen difference was
`results.semantic_only.3.per_query[0].intra_list_similarity`:
`0.37350100528591557` versus frozen `0.3735010052859155`.

Runtime records, complete baseline/fixed Fast gate logs and all 76 numerical
differences are retained locally in ignored `artifacts/issue-21/`. No audio or
model inference/download was needed. Kernel overrides were confined to these
local subprocesses; CI uses its supported native numerical path.

The local controls used the repository's Python 3.11 environment. After verifying
that the host supports both kernels, the equivalent commands are:

```powershell
$env:OPENBLAS_NUM_THREADS = '4'
foreach ($diagnosticCore in @('Cooperlake', 'Zen')) {
    $env:OPENBLAS_CORETYPE = $diagnosticCore
    python -c "import numpy as np; np.show_runtime()"
    python scripts/ci_checks.py fast
}
Remove-Item Env:OPENBLAS_CORETYPE
Remove-Item Env:OPENBLAS_NUM_THREADS
```

## Change and controls

The policy in [docs/ci.md](../ci.md#frozen-role-metric-numerical-reproduction)
allows finite float differences of at most `1e-15`, with zero relative tolerance,
only at the two diagnostic paths under `results.<method>.<k>` for `k=1,3,5`.
The test recursively compares keys, types, list lengths/order and all remaining
values exactly. Rankings and the original Issue #6 metrics retain exact checks.
No production arithmetic, config, frozen labels, signals, metrics or rankings
were edited. The exact skip allowlist and model/index failure behavior are intact.

Eight policy tests exercise positive one-ULP changes at both diagnostic paths,
the tolerance boundary, and negative controls for larger similarity differences,
one-ULP Recall/mAP/paired/bootstrap changes, `null`, non-finite values, JSON
numeric types, missing/extra keys, list order/length, package/query identity,
label/signal hashes, config fingerprints, ranking ID/hash/order and score.
An identically named field outside the allowed paths remains exact.

The fixed Fast gate runs 77 ordinary tests with exactly the same three audited
model skips, five research tests with zero skips, and both schema comparisons.
Both locally selected kernels pass. The underlying raw diagnostic differences
remain visible in the recorded comparison; they were not rounded away or used
to regenerate the frozen reference.

Dependency consistency (`uv pip check`) passes and every installed locked
package version matches the unchanged snapshot. The manifest
`--require-all-eligible` and ranking-config validation CLIs pass, as does
`git diff --check`. The submitted change contains only test and documentation
files; tracked benchmark evidence and workflow/environment settings are unchanged.

## Limits

The tolerance is justified by the observed frozen-vector computation, rather
than claiming bitwise reproducibility or a universal BLAS error bound. Larger
differences or differences in ranking scores/order still fail. Other kernels
and future benchmark inputs need fresh evidence if they fail the gate. No
unsupported CPU kernel is forced on Actions and no global environment override
is introduced. Real-model behavior was not changed or revalidated by this fix.
