# VeriGreen demo app

Streamlit skeleton. It reads only committed files in `data/gold` and `data/silver` (`app/loaders.py` refuses any other
path). No prices, PDFs, `data/bronze`, network calls or tokens. It does not import `verigreen` or `qiskit`.

## Environment

A side environment outside the repo, so the project pins in `pyproject.toml` and `uv.lock` are untouched.

Installed versions: Python 3.12.11, streamlit 1.65.0, pandas 3.0.6, numpy 2.5.3. These differ from the project pins
(pandas 3.0.2, numpy 2.4.4) on purpose: the app only reads CSV and JSON, and nothing in it imports `verigreen` or
`qiskit`.

```
uv venv --python 3.12 <venvs>\verigreen-app
uv pip install --python <venvs>\verigreen-app\Scripts\python.exe streamlit pandas
```

The Hardware page reads `data/gold/hardware_runs_fy2024.csv` and `hardware_distribution_fy2024.csv`, written in the project environment by `scripts/hardware/export_hardware_summary.py` (the app environment has no qiskit); re-run it if `data/hardware/` changes.

## Run (from the repo root)

```
<venvs>\verigreen-app\Scripts\python.exe -m streamlit run app/streamlit_app.py --server.address localhost
```

## Smoke test

```
<venvs>\verigreen-app\Scripts\python.exe app/test_app_smoke.py
```
