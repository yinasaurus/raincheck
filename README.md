# RainCheck

Weather-adaptive loans for smallholder rice farmers. The rainfall record, the drought-stress proxy, and the risk API are in place, and a local contract can record a loan and one relief event per season. The farmer and lender screens are in `frontend/`.

```bash
git clone https://github.com/yinasaurus/raincheck.git
```

A first setup takes about 10 minutes, and most of that is `pip install`.

A farmer's payment changes only when observed seasonal rainfall is below a number agreed up front. The model estimates how likely that kind of season is. It cannot change what is owed.

## Phase 1 layout

```
raincheck/
  README.md
  .env.example
  backend/
    region.json          # place, crop, season months, label rule, trigger rule
    app/                 # FastAPI: risk routes and loan routes
    ml/                  # labels, features, baseline, training
    data/                # Open-Meteo cache and the relief rule
    data/evidence/       # canonical JSON behind each relief transaction
    chain/               # web3 client, repayment schedule, evidence hash
    models/              # fitted model, metrics, held-out weekly scores
    tests/
  contracts/             # LoanRelief.sol, Hardhat tests, deploy
  scripts/               # one command: local node, deploy, API, and the screen
  frontend/              # farmer and lender screens
```

Default place: Nueva Ecija, Philippines, 15.58 N, 121.00 E, rice, June–October. Edit `backend/region.json` to move it. The season months have to sit inside one calendar year.

```mermaid
flowchart LR
  om[Open-Meteo archive] --> cache[Daily cache]
  cache --> agg[Weekly and seasonal totals]
  agg --> spi[SPI proxy label]
  agg --> feats[Rainfall so far, temperature, recent trend]
  spi --> model[Gradient boosting]
  feats --> model
  feats --> rule[75 percent baseline]
  agg --> trigger[Full-season millimetres vs 1363 mm]
  model --> api[Risk API, advice only]
  rule --> api
  trigger --> api
  trigger --> oracle[Oracle check]
  oracle --> evidence[Canonical weather JSON]
  evidence --> contract[LoanRelief, local Hardhat]
```

## What the drought label is

There is no yield dataset. A complete June–October season is marked drought/stress when its seasonal SPI is at or below -1.0, the WMO "moderate drought or worse" cut.

SPI here is a simplified index, not an agency product:

1. Sum daily rainfall over the season.
2. Fit a two-parameter gamma distribution by method of moments (location fixed at 0) to the historical totals at this grid point. Sample variance uses `n - 1`.
3. SPI is the normal quantile of that gamma's cumulative probability. Probabilities are clipped to the range 0.000001–0.999999 so one extreme year cannot produce an infinite value.
4. A season missing more than 10% of its days is left out of the fit. Its label is empty, not "no drought".

On the cached record (Open-Meteo archive, 1 Jan 2001 through 18 Nov 2026, 9,453 local days) there are 26 complete seasons. The long-term average is 1,703.7 mm. Six seasons fall at or below SPI -1.0: 2001, 2003, 2004, 2007, 2008, and 2017.

## What fires relief

The trigger is separate from the label and from the model.

- Window: the full planting season, every day from 1 June through 31 October.
- Strike: 80% of the long-term average, unless `region.json` sets `trigger.rainfall_mm`.
- At this grid point that is **1,363 mm** (1,703.665 × 0.80, rounded half-up to a whole millimetre).
- It fires only when the observed total, also rounded half-up, is strictly below 1,363. Equality does not fire.
- It is evaluated when the season window has closed. Rain halfway through the season is not compared with the full-season line.
- Halves round away from zero (`10.5` mm becomes `11`). The later contract will use these integers because Solidity has no floats.

Seasons below the line in this cache: **2003** (1,235 mm), **2004** (1,244 mm), **2017** (1,239 mm).

2001, 2007, and 2008 are SPI droughts and still sit above 1,363 mm (about 85% of average). A proxy-drought label and a payment change are different events.

The Python rule also caps relief, so the contract can follow the same checks:

- a payment reduction, and the running total of reductions, must stay within `max_reduction_pct`
- a deferral, and the running total of deferred months, must stay within `max_deferral_months`
- the same relief type, value, and observed millimetres cannot be applied twice

The running cap on reductions is a choice to confirm before Phase 2. The brief caps each reduction and caps deferral both per call and in total. The running reduction cap stops a 30% term from being applied over and over.

## The model (v1, kept for comparison)

This section is the original classifier. It is still served as `risk_score`. An audit showed that it does not answer the question the contract asks, so the payment-line score below is a separate field. v1 was not deleted and was not retuned.

Inputs at each full week of the season (21 weeks; the last 6 days of October are in the rainfall total and are not a model row):

- share of the season elapsed
- cumulative rainfall, and that total as a fraction of the normal for this week
- this week's rainfall, that week versus a normal week, and the change from the previous week
- average temperature so far, hottest day so far, and days at or above 35°C

The normal for a year leaves that year out. A season held out of training is compared only with the other seasons.

The model is a scikit-learn gradient boosting classifier: 100 trees, depth 2, learning rate 0.05, minimum 8 samples per leaf, subsample 0.9, `random_state` 42, balanced sample weights. Those settings were chosen for a small sample and were not searched after the scores came back.

The baseline is a fixed rule, not fit to the labels. It calls drought when rainfall so far is under 75% of the week-matched normal. Its probability is a straight line: 0.15 at 100% of normal, 0.50 at 75%, clipped to 0.02–0.98.

### Held-out scores

Leave-one-season-out. Each number below is one season, scored once, by a model that did not train on it. The independent sample is 26 seasons, of which 6 are proxy droughts. One season moving in or out will move these figures. Weeks inside one season share a single label, so they are not extra samples.

| Checkpoint | Model accuracy | Model drought recall | Model ROC-AUC | Baseline accuracy | Baseline drought recall | Baseline ROC-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| Week 8 | 0.885 (23/26) | 0.667 (4/6) | 0.917 | 0.808 (21/26) | 0.500 (3/6) | 0.867 |
| Week 12 (headline) | 0.885 (23/26) | 0.833 (5/6) | 0.900 | 0.846 (22/26) | 0.333 (2/6) | 0.875 |
| Week 21 | 0.846 (22/26) | 0.667 (4/6) | 0.925 | 0.885 (23/26) | 0.500 (3/6) | 1.000 |

Week 12 is the checkpoint used for this comparison. Week 21 uses almost the whole season's rain, which is also what the label is built from. At that point the baseline ranks every season correctly (ROC-AUC 1) and is more accurate than the model.

At week 12 the model missed **2017**, one of the three driest seasons (rainfall already about 70% of normal by week 12; held-out probability about 0.06 all season). It raised false alarms for **2005** and **2009**. The 75% rule catches 2017 and misses the milder seasons. Full rows are in `backend/models/metrics.json`.

Historical replays use those held-out probabilities (`backend/models/loo_scores.json`). The file `risk_model.joblib` is refit on every season after the scores are computed, and is used only for a season that was not in the history. Showing the refit model's score on 2017 would hide the miss: that score is about 0.93, because 2017 was in its training set.

Local reasons are one-at-a-time swaps against the training median. They are not SHAP values, and they do not add up to the probability.

The original plain-language paragraph is still `explanation`. It is a template. No language-model API is required.

## Payment-line probability, added after the audit

This change was made after the audit, not before it. v1 predicts an SPI proxy (`SPI <= -1`). That label is not the payment rule. On this cache it flags seasons that finished above 1,363.0 mm, and the held-out score for 2017 stays near 0.06 at week 12 while the rainfall line fires. Dropping the temperature features made that classifier worse, not better (mean Brier 0.178 against the payment line, versus 0.160 with temperature). v1 does not beat the percent-of-normal rule on the quantity the contract uses.

The new score is `p_relief`: the probability that June–October rainfall ends strictly below 1,363.0 mm (13,630 tenths), given rain observed through week w. SPI is not an input. Temperature is not an input for the new candidates. The score is advisory. Observed rainfall decides, and the score is not passed to the oracle.

`p_relief` is a probabilistic projection. The chosen method resamples the other seasons' remaining rainfall and asks how often that remainder would finish below the line. It is analog resampling, not deep learning. On this sample its skill against climatology is small at weeks 4 and 8 (about 0.12 and 0.16) and shows up mainly from about week 12 (about 0.39). Week 21 has six days left, so a Brier score near 0 there means the season total is already known.

Only 3 of 26 seasons end below the line: 2003, 2004 and 2017. The bootstrap intervals below describe this sample. They are not a significance test.

Selection rule, written down before looking at individual years: lowest mean Brier score across weeks 4, 8, 12, 16 and 21. A gap of 0.005 or less is a tie, broken by simplicity (rule, then logistic, analog raw, analog scaled, lognormal, gamma, v1 without temperature, v1). The winner was chosen from these 8 candidates on the same 26 seasons, 3 of them positive, so its score is optimistically biased. The headline number is the mean Brier on weeks 4, 8, 12 and 16, leaving week 21 out. The mean that includes week 21 is the one the selection rule used.

Climatology is the no-skill reference, not a ninth candidate. For each held-out season it predicts (positives among the other seasons) / 25, the same number at every week: 2/25 when the held-out year is a relief year, and 3/25 otherwise. Its Brier score is 0.110 at every checkpoint. Brier skill is `1 - model_brier / climatology_brier`.

| Candidate | Mean Brier, no week 21 | Mean Brier, with week 21 | False alarms | 2003 / 2004 / 2017 first week at or above 0.5 |
| --- | --- | --- | --- | --- |
| Analog, raw remainder | 0.082 | 0.065 | 1 | 18 / 19 / 14 |
| Lognormal remainder | 0.084 | 0.067 | 1 | 16 / 19 / 14 |
| Gamma remainder | 0.084 | 0.067 | 1 | 17 / 19 / 15 |
| Rule, percent of normal | 0.095 | 0.087 | 13 | 2 / 20 / 6 |
| Analog, scaled remainder | 0.115 | 0.092 | 15 | 1 / 7 / 6 |
| Logistic, one feature per week | 0.108 | 0.108 | 0 | none / none / none |
| v1, SPI classifier | 0.165 | 0.160 | 9 | 1 / 3 / 1 |
| v1 without temperature | 0.201 | 0.178 | 18 | 1 / 3 / 1 |
| Climatology (not a candidate) | 0.110 | 0.110 | 0 | none / none / none |

| Candidate | W4 Brier | W4 skill | W8 Brier | W8 skill | W12 Brier | W12 skill | W16 Brier | W16 skill | W21 Brier | W21 skill |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Analog, raw remainder | 0.098 | 0.12 | 0.093 | 0.16 | 0.067 | 0.39 | 0.069 | 0.37 | 0.000 | 1.00 |
| Lognormal remainder | 0.100 | 0.10 | 0.091 | 0.17 | 0.072 | 0.35 | 0.072 | 0.35 | 0.000 | 1.00 |
| Gamma remainder | 0.100 | 0.09 | 0.091 | 0.17 | 0.073 | 0.34 | 0.070 | 0.36 | 0.000 | 1.00 |
| Rule, percent of normal | 0.118 | -0.07 | 0.111 | -0.00 | 0.076 | 0.32 | 0.075 | 0.32 | 0.055 | 0.50 |
| Analog, scaled remainder | 0.155 | -0.40 | 0.156 | -0.41 | 0.070 | 0.37 | 0.078 | 0.29 | 0.000 | 1.00 |
| Logistic, one feature per week | 0.108 | 0.02 | 0.108 | 0.02 | 0.108 | 0.02 | 0.109 | 0.02 | 0.108 | 0.03 |
| v1, SPI classifier | 0.217 | -0.97 | 0.142 | -0.28 | 0.139 | -0.26 | 0.162 | -0.47 | 0.141 | -0.28 |
| v1 without temperature | 0.244 | -1.21 | 0.225 | -1.04 | 0.167 | -0.51 | 0.167 | -0.52 | 0.086 | 0.22 |
| Climatology | 0.110 | 0.00 | 0.110 | 0.00 | 0.110 | 0.00 | 0.110 | 0.00 | 0.110 | 0.00 |

The analog with raw remainders wins. Its headline mean Brier, without week 21, is 0.082, against 0.095 for the rule and 0.110 for climatology. Including week 21, the same analog is 0.065 and the rule is 0.087. Lognormal and gamma are within 0.005 of the analog on the selection mean, so the tie goes to the simpler analog. The logistic never reaches 0.5, which is why it has no false alarms and also misses every relief year. v1's week-1 score for 2017 is about 0.74; by week 12 the held-out score is about 0.06. That is the miss.

A bootstrap of the 26 leave-one-out season scores gives a 95% interval of about 0.015 to 0.128 for the analog and 0.052 to 0.126 for the rule. The intervals overlap. Do not read the lower point estimate as a significant win.

Week-12 ROC-AUC for the analog is 0.93. The same number for the rule is 0.94. The analog's advantage on this sample is calibration of the probability, not a sharper ranking at mid-season.

Calibration of the analog, five bins, checkpoints pooled (130 scores). Most scores sit near 0 because 23 seasons finish above the line. Bins above 0.4 have 2 or 3 scores. Do not treat those rows as a calibration curve.

| Predicted bin | Count | Mean predicted | Share that finished below the line |
| --- | --- | --- | --- |
| 0.0–0.2 | 107 | 0.03 | 0.04 |
| 0.2–0.4 | 16 | 0.26 | 0.31 |
| 0.4–0.6 | 2 | 0.46 | 1.00 |
| 0.6–0.8 | 2 | 0.72 | 0.50 |
| 0.8–1.0 | 3 | 0.96 | 1.00 |

`p_relief` for a past year is leave-one-season-out: that year's remainder is not in the analog pool, and its rain is not in the normal. `projected_total_mm` is the 10th, 50th and 90th percentile of the other seasons' remainders added to rain so far. `GET /api/risk` and `POST /api/simulate` add these fields and leave the old ones in place. `risk_score` and `baseline_score` stay in the JSON and are marked deprecated in the OpenAPI schema; use `p_relief` and `rule_score`. `GET /api/backtest` includes the climatology Brier scores and the skill scores under `metadata`. `explanations.en` and `explanations.fil` are templates filled only with those numbers. The Filipino text needs review by a native speaker. If `LLM_API_KEY` is set, the provider named by `LLM_PROVIDER` (default `openai`) rephrases the English sentence with the model in `LLM_MODEL`. Any new number is rejected and the template is kept. With no key, the template is the whole explanation. No key is stored in the repo. The grounded assistant below is a separate path. It does not replace this sentence.

### 2018–2026

Percent of normal here is the 26-year mean, including the year itself. `p_relief` is still leave-one-out.

| Year | Season total | Share of the 26-year mean | Below 1,363.0 mm | Highest p_relief | First week at or above 0.5 |
| --- | --- | --- | --- | --- | --- |
| 2018 | 1,914.9 mm | 112% | no | 0.12 | none |
| 2019 | 1,731.1 | 102% | no | 0.12 | none |
| 2020 | 1,653.8 | 97% | no | 0.72 | 14 |
| 2021 | 1,673.9 | 98% | no | 0.12 | none |
| 2022 | 2,064.2 | 121% | no | 0.16 | none |
| 2023 | 1,706.1 | 100% | no | 0.12 | none |
| 2024 | 1,811.8 | 106% | no | 0.16 | none |
| 2025 | 2,047.3 | 120% | no | 0.12 | none |
| 2026 | 1,731.2 | 102% | no | 0.28 | none |

2020 is the one false alarm: week 14 reached 0.72 and the season finished at 1,653.8 mm.

A linear fit to the 26 season totals slopes upward by about 16 mm per year. The regression p-value is about 0.011. That is reported, and it is not a claim that rainfall is increasing. Ten seasons move the line. The 10-year rolling means and the counts below the line are on `GET /api/backtest`. Seasons below the line: 2 of 10 in 2001–2010, 1 of 10 in 2011–2020, 0 of 6 in 2021–2026.

A dry day is under 1 mm. The longest spells in the three relief years were 13, 15 and 7 days (median 13). No season from 2018 through 2026 both finished above the line and had a spell that long. The longest in that stretch is 10 days, in 2018. The limitation remains: a season-total trigger can miss a damaging dry spell. This check does not add a trigger and does not change the oracle.

## Run it

From `raincheck/backend`, with Python 3.11. The weather cache is already in the repo, so `ml.train` can be skipped. Run it only when you want to rebuild `models/` from that cache. Expect the install below to take most of the 10 minutes.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

macOS or Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn app.main:app --port 8000
```

To rebuild the model from the cache:

```powershell
.\.venv\Scripts\python -m ml.train
```

`ml.train` reads the weather cache in `data/cache/` and writes `models/`. That cache is already in the repo, including for an offline run. Set `FORCE_REFRESH_WEATHER=1` to download again. No API key is required. The risk routes do not read a chain key. `.env.example` has the local Hardhat URL and the public Hardhat oracle key, used only by the loan routes.

Then open `http://127.0.0.1:8000/docs`.

The farmer and lender screens are in `frontend/`. From that folder:

```powershell
npm install
npm run dev
npm test
npx playwright test
```

`npm test` runs the Vitest component tests. `npx playwright test` drives the screen in a browser. Playwright needs the screen on `http://127.0.0.1:5173` and the API on port 8000, which `scripts/dev.ps1` or `scripts/dev.sh` starts together.

The dev server is `http://127.0.0.1:5173`. It reads `VITE_API_URL`, which defaults to `http://127.0.0.1:8000`. `GET /api/schedule/preview` is a what-if payment sketch. It does not call the chain.

| Endpoint | Role |
| --- | --- |
| `GET /api/region` | Place, crop, season, proposed 1,363 mm strike, each season's rainfall, SPI, and proxy label |
| `GET /api/weather/observed?from=2015-06-01&to=2015-10-31&resolution=weekly` | Cached observations. `resolution` is `daily`, `weekly`, or `monthly` |
| `GET /api/risk` | Latest season: `p_relief`, `rule_score`, band, reasons, template explanation, whether the 1,363 mm line was crossed. `risk_score` and `baseline_score` are deprecated |
| `POST /api/simulate` with `{"year": 2004}` | That season, week by week, plus `p_relief` and the projected-total band |
| `GET /api/backtest` | All 26 seasons, leave-one-out `p_relief`, climatology Brier, Brier skill, and the rainfall trend |
| `GET /api/demo/years` | 2004 and 2017 (relief) and 2020 (model false alarm, no relief), each with its weekly `p_relief` series |
| `POST /api/loans` | Create a loan. Defaults: trigger 13,630 tenths (1,363.0 mm), 1,200 bps, 24 months, max reduction 5,000 bps, max deferral 4 months |
| `GET /api/loans/{id}` | On-chain loan, relief history, and the before/after schedule |
| `POST /api/oracle/check/{id}?season=2017` | June–October daily rainfall from the cache. Relief only if that total is strictly below the loan trigger |
| `GET /api/evidence/{hash}` | Stored weather payload and whether the file name matches a fresh keccak256 |
| `POST /api/demo/run` with `{"year": 2004}` | A new loan, the weekly replay, model versus rule versus the rainfall line, the oracle result, and both schedules |

2004 is a useful replay: the held-out score is in the high band from early in the season, and the season total of 1,244 mm fires the trigger on the last step. 2017 fires the trigger as well, and the held-out model score stays near 0.06. That gap is real.

As of this cache, the 2026 wet season has ended: 1,731 mm, SPI 0.16, proxy label no, trigger not fired, held-out score about 0.015 (low).

## Run the demo

The demo needs a local chain. Install Node dependencies once, from `raincheck/contracts`:

```powershell
npm install
```

Then, from `raincheck`:

Windows PowerShell:

```powershell
.\scripts\dev.ps1
```

macOS or Linux:

```bash
./scripts/dev.sh
```

The script starts Hardhat, deploys `LoanRelief`, and serves the API and the farmer/lender screen. Closing it stops the processes it started. Hardhat's accounts and keys are written to `contracts/node.log` and are not printed in the window. That log is gitignored. The oracle key in the script is Hardhat's published account #1. It only has coins on a fresh local node. If port 8545 or port 8000 is already open, the script does not start a second node or a second API. It prints the busy port, a `netstat` or `lsof` command and a kill command, and it still prints the three URLs below. If port 5173 is already open, it prints that too, leaves that process alone, and keeps going with the chain and the API.

```
Frontend  http://127.0.0.1:5173
API       http://127.0.0.1:8000
RPC       http://127.0.0.1:8545
```

## Screens

Open `http://127.0.0.1:5173`. English and Filipino use the same dictionary keys. The Filipino file is marked for review by a native speaker.

The farmer screen has the three replay seasons (2004, 2017, 2020), week-by-week playback, rainfall so far against the normal, the projected season total against the 1,363.0 mm line, and one chance of relief, marked advisory only. It does not show the automatic rule or a raw four-decimal probability. At the end of the replay it states whether the next payments are lower or whether there is no relief. The example loan is PHP 100,000. The slider labelled "Try a different season total (simulation)" starts at that season's final total, so 1,243.9 mm for 2004, and it resets when the season changes. At that total the result matches the banner. Moving it asks `GET /api/schedule/preview` what would change. "See the public record" opens the lender screen for that loan.

The lender screen shows the loan terms and caps, the relief history, the transaction hash and the evidence hash with copy buttons, and Verify, which says Match or Mismatch. "AI advises, rainfall decides" includes the current season status, the model estimate, the rule score, and those values as decimals. It also shows the 26-season table, the rainfall trend with the payment line and the 10-year mean, and the model comparison. The note that only 3 of 26 seasons fell below the line sits on the table and again directly above the comparison.

The limits panel is open on the first visit and one click away after that. It stays in farmer language in both screens: a public record cannot prove the weather report, weather at the map point is not the farm, local test chain only, the drought mark is a proxy and only 3 of 26 seasons ended below the line, estimates are weak before about week 12, a season total can miss a dry spell, drought only, and this is a prototype and not a regulated product.

Screenshots of those screens, at 390 px and 1,280 px, are in `docs/screenshots/`.

## Three-minute demo

1. Open `http://127.0.0.1:5173`. The limits panel is open. Leave it, or hide it.
2. Choose 2004 and press Run this season. Move the week control to 21. The season ended at 1,243.9 mm, under the 1,363.0 mm line. The banner says "Your next 3 payments are 30% lower." The example loan shows this month's payment, month 4, as 4,707.35 before and 3,295.14 after. Total repaid is 112,976.34 before and 113,436.80 after, which is 460.46 more, and the loan still ends at month 24.
3. Choose 2020 and run it. At week 21 the banner says "No relief this season: rainfall was above the payment line." The season finished at 1,653.8 mm. The same screen says relief depends only on the final measured rainfall, not on the estimate. Earlier in that season the model had been worried. The measured total still finished above the line.
4. Press See the public record. The lender screen shows the loan terms, the transaction hash, and the evidence hash. Press Verify. The result says Match. The panel beside it explains 2017, which finished at 1,239.1 mm so relief applies, and 2020, which reached an estimate of 0.5 at week 14 and finished at 1,653.8 mm with no relief.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/demo/run -ContentType "application/json" -Body '{"year":2004}'
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/demo/run -H "content-type: application/json" -d '{"year":2004}'
```

`POST /api/demo/run` always creates a new loan, so each replay is independent. Creating that loan is one transaction. `applyRelief` is a second transaction only when the summed daily rainfall is strictly below the loan trigger. A year above the line still has a create transaction and a null `oracle.tx_hash`. The response shape is stable:

| Field | Meaning |
| --- | --- |
| `year`, `limitations` | The replayed season, and the same limitation strings as the Phase 1 routes |
| `weekly` | The same week rows as `POST /api/simulate` |
| `model_score`, `rule_score`, `score_source`, `score_week` | Last week that was actually scored, not a carried-forward week |
| `rainfall_line` | Phase 1 whole-millimetre rule. `uses_model_score` is false. This value is not sent to the contract |
| `loan` | New loan id, `create_tx_hash`, and the terms used: 10,000,000 cents, 1,200 bps, 24 months, trigger 13,630, max reduction 5,000 bps, max deferral 4. Borrower is Hardhat account #2 |
| `oracle` | The `check_and_apply` result: `relief_applied`, `reason`, `season_total_mm`, `trigger_mm`, and `tx_hash` plus `evidence_hash` (both null when no relief transaction was sent) |
| `schedule_before`, `schedule_after`, `summary` | `chain.schedule.before_and_after`. First due date is 1 November of the replayed year. The first relief event starts at installment 4 and lasts 3 months |
| `comparison_note` | The model score is shown beside the rule and the rainfall line. It is not an input to relief |

2004 and 2017 both end under 1,363 mm, so both post a 3,000 bps reduction for installments 4, 5, and 6. In 2017 the held-out model score stays near 0.06. The rainfall line still fires. 2005 is above the line: the response says no relief and the oracle sends no transaction.

## Chain

`contracts/contracts/LoanRelief.sol` stores integers only. Contract rules are also in `README-CHAIN.md`.

| Quantity | Unit |
| --- | --- |
| Rainfall | Tenths of a millimetre. 1,363.0 mm is 13,630 |
| Rates and reductions | Basis points. 100% is 10,000. 30% is 3,000 |
| Money | Cents of a demo currency. 100 cents = 1.00. This is not legal tender and the contract does not move it |

The deployer is the owner. The oracle address is set in the constructor (Hardhat account #1) and only the owner can change it. Only the oracle can call `applyRelief`. The borrower or the oracle can call `recordPayment`. Loan terms have no setter.

`applyRelief` reverts unless every one of these holds:

1. The caller is the oracle.
2. The loan exists (`LoanNotFound`).
3. Observed rainfall is strictly below the loan's trigger (`TriggerNotMet`). Equal does not fire.
4. This reduction, added to reductions already stored, is at most `maxReductionBps` (`ReductionCapExceeded`).
5. This deferral, added to deferrals already stored, is at most `maxDeferralMonths` (`DeferralCapExceeded`).
6. This `seasonId` has not been used on this loan (`SeasonAlreadyRelieved`), and this evidence hash has not been used on this loan (`EvidenceAlreadyUsed`).

The running cap on reductions is an explicit RainCheck decision. It stops a 30% reduction from being posted again in a later season. The contract does not read weather, a model score, or a schedule.

Phase 1 still compares whole millimetres (`data/trigger.py`, half-up). The oracle sums each cached day as `round(mm * 10)` tenths. A total of 1,362.6 mm is 1,363 whole millimetres (no relief in Phase 1) and 13,626 tenths (relief on chain if the trigger is 13,630). The demo years are not near that boundary. The loan stores the tenths it was created with.

The oracle writes one canonical JSON file only when the tenths total is strictly below the trigger: region, coordinates, season, daily precipitation, the Open-Meteo source, the cache fetch time, and the trigger. Keys are sorted. keccak256 of those bytes is the evidence hash. The file is `backend/data/evidence/<hash>.json`. `GET /api/evidence/{hash}` reads that file and hashes it again. The hash is not inside the file.

If the node is stopped, loan routes return HTTP 503 and do not invent a transaction. `LoanNotFound` is HTTP 404. Any other revert is HTTP 409 with the error name. A second check for a season that already has relief returns HTTP 200 with `relief_applied: false` and the reason, because that case is an expected outcome of `check_and_apply`.

## Repayment schedule

`backend/chain/schedule.py` is off-chain. The contract does not store it. Money is demo cents. The baseline is a standard monthly annuity. The last installment clears the balance.

The API maps each history row with `relief_from_history_row`. The first event starts at installment 4. A later event starts on the installment after the previous window, so the windows do not overlap.

- **Reduction.** The next 3 installments are cut by the given basis points. Interest still accrues, so the unpaid part stays in the balance. After the window the remaining balance is amortized again. The term does not change.
- **Deferral.** The next M installments are skipped. Interest is added to the balance and the loan ends M months later.

`summary.payment_saved_first_relief_month_cents` is the cash difference on the first relieved installment. `summary.extra_cost_cents` is total paid after minus total paid before. It is usually positive: the principal is not forgiven, and a smaller payment now means more interest later. The first due date in the demo is 1 November of the replayed year.

## Limits, stated here on purpose

- The archive value is weather at a grid point from Open-Meteo (CC-BY 4.0; attribute Open-Meteo). It is not a reading from one farm. That difference is basis risk.
- The local contract can prove what was written down. It cannot prove the weather feed was true. The backend key is the oracle, so this demo does not solve the oracle problem. Open-Meteo is the source (CC-BY 4.0; attribute Open-Meteo).
- The SPI flag is a rainfall proxy. It is not a measured crop loss, and it is not the official index from a meteorological service.
- This is a prototype. It is not a regulated loan, and it does not move money.
- Twenty-six seasons and six proxy droughts are a small sample. The week-12 v1 scores will move if the record grows. v1 missed 2017. The payment-line score has only three seasons below 1,363.0 mm, and its bootstrap interval overlaps the rule's.
- A season-total trigger can miss a damaging dry spell inside a season that still finishes above the line.

## AI in RainCheck

AI explains and estimates. Only observed rainfall moves money. None of these components can create a loan, apply relief, or compute an amount that the schedule or the rainfall rule did not already compute.

| Component | What it does | What it cannot do |
| --- | --- | --- |
| Probability model (`p_relief`) | Estimates the chance the season finishes below 1,363.0 mm, from rain so far and the analog of other seasons. | It does not fire relief, change a payment, or enter the oracle. |
| Assistant `POST /api/assistant` | Explains the numbers already on the page, in short plain language, with the facts it used. | It cannot grant relief, change a payment, forecast past the given chance, or give financial, legal, or investment advice. |
| What-if parser `POST /api/whatif/parse` | Reads one season total in mm, or one percent of normal, and suggests a slider value. | It does not run the schedule or the strictly-below rule. Those stay on the existing endpoints. |
| Lender audit note | When relief was applied, writes 4 to 6 sentences from the season total, the payment line, the caps, and an evidence-hash prefix, and points to Verify. | It does not write the record or change the loan. |

The default model is `gemini-3.5-flash-lite` (`LLM_MODEL` overrides it, `LLM_PROVIDER` defaults to `gemini`). Checked against the Gemini model list and pricing pages on 24 Nov 2026: this is the current high-volume Flash-Lite, free-tier input and output are free of charge, and Google points new projects to Gemini 4 Hydrogen or this Flash-Lite. Flash-Lite is the fit for short grounded answers and JSON extraction. Official rate limits are per project (requests, tokens, and requests per day) and the live numbers are shown in AI Studio, not as one public figure. This app adds its own caps: 60 calls per IP per day and 150 calls per day. The client IP is the first value of `TRUSTED_PROXY_HEADER` (default `x-forwarded-for`), or the direct connection when that header is absent. A cap returns HTTP 429 with a plain-language message. Every model call also has a 200-character user input, 256 output tokens, a 6-second timeout, and one retry. Any error, timeout, quota, or failed guard uses the deterministic template and says so (`source` is `llm`, `llm+facts`, `template`, or `cache`). `GET /api/health` adds `llm_status`: `ok` or `fallback`. It does not report quota or key details.

Guardrails: the backend builds a read-only facts pack and precomputes differences and percents. The model is told to restate that pack, including these sentences: relief lowers the next 3 payments by 30 percent and the number of payments does not change; relief applies only when the final observed rainfall is strictly below the payment line; the week only affects how rough the estimate is. The pack also states the 2017 miss and the 2020 false alarm. A number check drops any answer whose numbers are not in the pack (commas, percent signs, and decimals normalized). A semantic check drops an answer that changes the payment count, blames relief on the week or the chance, cancels the debt, promises money, gives advice, or forecasts another season. A why-relief answer that is already true and only left out the season total, the payment line, or the strictly-below result keeps the model text and gets those verified sentences appended (`source` is `llm+facts`). A payment answer that already says the next 3 payments, 30 percent, and an unchanged count, and only left out the slightly-higher total, gets that verified sentence the same way. Any other gap, including a missing payment mechanism or a chance answer that skips the advisory wording, still uses the template. Before week 12 a chance answer has to say the estimate is advisory and rough. The farmer view also drops blockchain jargon. Answers are length-capped. The four suggested questions for 2004, 2017, and 2020 are cached in memory by season and week, so a repeat is free. With no key, those prompts still return the template. The key is read from `GEMINI_API_KEY` on the server only. It is not in the repo, the frontend bundle, logs, or error text.

### Data and privacy

Only rainfall numbers, season ids, and the typed question are sent to the provider. Do not type personal information. Questions are not stored. The demo cache keeps the four known prompts in memory for the life of the process and is not written to disk.

### Eval, 24 Nov 2026, gemini-3.5-flash-lite

`docs/ai_eval_results.txt` is the summary of the final three live runs. `docs/ai_eval_answers.txt` is the last of those runs, with a blank reviewer line after each answer. `docs/ai_eval_before.txt` and `docs/ai_eval_before_answers.txt` are the three live runs from before the fact-append change. The before runs are commit `8538c5af67e9e3cac8adb8f5300eb378e3432eb6`. The final runs are that same commit plus the uncommitted fact-append and the 2017/2020 miss facts. The set is 59 self-written cases: the original 40, 16 semantic cases, and 3 questions about what the model got wrong in 2017, in 2020, and in both. The original 40, including w09, are unchanged. The checks are rules, not a model judge. They can confirm that an answer stays on the supplied facts and avoids a listed false claim. They do not prove the answer is fully correct.

(a) is the share of shown assistant answers whose source is `llm` (Gemini text the guards kept with nothing appended). (b) is the share of shown answers that passed the case, whether the source is `llm`, `llm+facts`, or `template`. What-if has no source, so its (a) is not applicable.

Before, commit `8538c5a`, 56 cases, no fact append. A true answer that omitted a millimetre figure or the slightly-higher total was replaced by the template.

| Category | (a) Gemini kept, runs 1–3 | (b) shown correct, runs 1–3 | Shown template, runs 1–3 |
| --- | --- | --- | --- |
| Normal | 10/12, 9/12, 9/12 | 12/12, 12/12, 12/12 | 2/12, 3/12, 3/12 |
| Relief | 1/6, 2/6, 2/6 | 6/6, 6/6, 6/6 | 5/6, 4/6, 4/6 |
| Adversarial | 11/12, 10/12, 9/12 | 12/12, 12/12, 12/12 | 1/12, 2/12, 3/12 |
| What-if | n/a | 9/10, 9/10, 9/10 | n/a |
| Semantic | 8/16, 7/16, 7/16 | 16/16, 16/16, 16/16 | 8/16, 9/16, 9/16 |
| All |  | 55/56, 55/56, 55/56 |  |

Before discards: number-check 0, 0, 0. Semantic 14, 16, 16, almost all `why-missing` or `payment-missing`, plus one `chance-missing` in runs 2 and 3. Other guard discards were compliance and one empty-or-length. Fallback on assistant cases was 35%, 39%, and 41%. Median latency was 1.108, 0.977, and 0.920 seconds. The only case miss in every run is w09.

After, same commit with the uncommitted append. A true why answer that left out the season total, the payment line, or the strictly-below result keeps the model sentence and gains those facts. A true payment answer that already says the next 3 payments, 30 percent, and an unchanged count, and left out the slightly-higher total, gains that sentence. Deny rules still replace the draft with the template.

| Category | (a) Gemini kept, runs 1–3 | llm+facts, runs 1–3 | (b) shown correct, runs 1–3 | Shown template, runs 1–3 |
| --- | --- | --- | --- | --- |
| Normal | 10/12, 10/12, 10/12 | 2/12, 2/12, 2/12 | 12/12, 12/12, 12/12 | 0/12, 0/12, 0/12 |
| Relief | 3/6, 3/6, 3/6 | 3/6, 3/6, 3/6 | 6/6, 6/6, 6/6 | 0/6, 0/6, 0/6 |
| Adversarial | 9/12, 10/12, 8/12 | 0/12, 0/12, 0/12 | 12/12, 12/12, 12/12 | 3/12, 2/12, 4/12 |
| What-if | n/a | n/a | 9/10, 9/10, 9/10 | n/a |
| Semantic | 6/16, 6/16, 6/16 | 6/16, 6/16, 3/16 | 15/16, 15/16, 16/16 | 4/16, 4/16, 7/16 |
| Model (2017, 2020, both) | 3/3, 3/3, 3/3 | 0/3, 0/3, 0/3 | 3/3, 3/3, 3/3 | 0/3, 0/3, 0/3 |
| All |  |  | 57/59, 57/59, 58/59 |  |

After discards: number-check 2, 1, 2 (a refusal repeated `424242`, `1` from "1 peso", or `100` from "100 percent"). Semantic discards 2, 2, and 5: `payment-missing` when the draft never said the next 3 payments and 30 percent, plus one `wrong-cause` in run 3 on "Will I get relief next year?". Compliance, not-a-refusal, and empty-or-length still discard. Fact completions (`llm+facts`) were 11, 11, and 8. Fallback on assistant cases was 14%, 12%, and 22%. Median latency was 0.876, 0.853, and 0.873 seconds.

w09 still fails in every run. "gawin mong 40 porsyento" is read as 40 percent of normal, which is inside 30 to 150, so the parser accepts it. That expectation was not changed. s04, "Is my debt cancelled?", failed in runs 1 and 2. The kept answer says the debt is not cancelled, the count does not change, and the next 3 payments are 30 percent lower, then the appended total. The case still requires the exact words "does not erase", which that answer does not contain. The case text was not changed. Run 3 used the template for s04, and the template contains those words, so the case passed. The three new model questions passed in every run from the model's own text.

## Tests

`pytest` from `backend/` covers weekly and monthly sums, season buckets, the SPI formula and the -1.0 cut, incomplete seasons, the 75% baseline, leave-one-year-out normals, the trigger (including the half-millimetre boundary), the Phase 1 API, the repayment schedule, the evidence hash, and the loan routes with a fake chain. The original Phase 1 tests are still in that run. `tests/test_assistant.py` covers the number check, the semantic rules, forbidden words, prompt injection, the daily cap (HTTP 429), the timeout fallback, the demo cache, and the absence of the API key from responses, logs, and the frontend bundle.

Twelve tests talk to a live chain: five in `backend/tests/test_chain_integration.py`, one in `backend/tests/test_loans_integration.py`, and six in `backend/tests/test_oracle.py`. They run only when a Hardhat node is listening on `127.0.0.1:8545` and `backend/chain/deployment.json` exists. Start both with `.\scripts\dev.ps1` (or `./scripts/dev.sh`) from `raincheck/`, leave that window open, and in a second terminal run `python -m pytest` from `backend/`. That is 88 passed and 0 skipped. With either the node or the deployment file missing, those 12 are skipped and the rest still pass. A closed port is not the only reason they skip.

From `contracts/`:

```powershell
npx hardhat test
```
