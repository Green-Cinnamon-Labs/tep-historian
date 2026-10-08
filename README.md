# tep-historian

Generic historian for the **TEP CPS Lab**. It collects every signal a plant publishes over OPC-UA and serves window statistics over HTTP. It's the middleware between the plant and the supervisory layer: Kubernetes never sees raw signals, only the verdicts that `plant-supervisor` derives from these aggregates.

```
tep-plant ──OPC-UA──▶ tep-historian ──HTTP──▶ plant-supervisor ──▶ Plant.status
```

It knows nothing about TEP. Every node under the `Signals` folder of the OPC-UA server becomes a series, keyed by its browse name (e.g. `xmeas.reactor.pressure`). Plant-specific knowledge lives only in the Kubernetes manifests (`CostFunction`, `OperatingPolicy`).

## API

| Method | Path         | Description                                                                 |
| ------ | ------------ | --------------------------------------------------------------------------- |
| GET    | `/healthz`   | Collection state: connected, last sample time, last error, number of series |
| GET    | `/signals`   | Keys available in the buffer                                                |
| POST   | `/aggregate` | Window statistics for the requested keys                                    |
| POST   | `/loop-performance` | Predictability Index (Bradu et al. 2017) of each requested control loop |

```bash
curl -s localhost:8090/aggregate -H 'content-type: application/json' \
  -d '{"keys": ["xmeas.reactor.pressure"], "window_s": 60}'
```

```json
{
  "window_s": 60,
  "connected": true,
  "signals": {
    "xmeas.reactor.pressure": {"count": 120, "mean": 2705.1, "std": 0.4, "min": 2704.3, "max": 2705.9, "last": 2705.2}
  },
  "missing": []
}
```

Unknown keys are listed in `missing`.

### Control-loop performance

`POST /loop-performance` computes, for each loop, the **Predictability Index** of Bradu et al. (2017): an autoregressive model is fitted to the error `e = SP − PV` and asked to predict it `b` samples ahead. PI ≈ 1 means a regular, predictable loop; PI ≈ 0 means an erratic error, like white noise. The historian only computes; judging against a threshold is the supervisor's job.

```bash
curl -s localhost:8090/loop-performance -H 'content-type: application/json' -d '{
  "window_s": 300, "sample_interval_s": 1,
  "loops": [{"name": "separator_level", "pv": "xmeas.separator.level", "sp": 50,
             "op": "valve.separator_underflow.position", "time_constant_s": 30}]}'
```

Per loop it returns `pi`, the raw ratio `σ²_r / mse` (`ratio`), `mse`, the residual variance, `sigma_op` (standard deviation of the controller output, for the article's variability gate), and the article's parameters `n`, `b = ceil(T / t_s)`, `m = 2b`. `pi` is `null` with a `reason` when it can't be computed (`too_few_samples`, `zero_error`, `missing_signal`).

The article prints the index as `σ²_r / mse` but describes PI = 1 for a predictable loop and 0 for white noise; that scale requires `1 − σ²_r / mse`, which is what is implemented (see `loop_performance.py`). A known key with no samples in the window returns `count: 0` and `null` statistics.

## Configuration

| Variable             | Default                                 | Description                 |
| -------------------- | --------------------------------------- | --------------------------- |
| `OPCUA_ENDPOINT`     | `opc.tcp://127.0.0.1:4840/tep/server/`  | Plant OPC-UA endpoint       |
| `SAMPLE_INTERVAL_MS` | `500`                                   | Collection period           |
| `RETENTION_S`        | `3600`                                  | How long samples are kept   |
| `PORT`               | `8090`                                  | HTTP port                   |

## Running

```bash
poetry install
poetry run tep-historian      # or: poetry run python -m tep_historian
poetry run pytest
```

Docker:

```bash
docker build -t tep-historian:latest .
docker run --rm -p 8090:8090 tep-historian:latest
```

## Known limitations

- Windows are measured in wall-clock time, so a 60 s window covers a different amount of simulated time depending on the plant's speed. The plant does publish simulated time as the `clock.t_h` signal, so windows in simulated time are a possible later change.
- Samples live in memory only; a restart empties the buffer.

## Tracking

Issues live in [spec-tennessee-eastman](https://github.com/Green-Cinnamon-Labs/spec-tennessee-eastman): epic #77, this repo #78.
