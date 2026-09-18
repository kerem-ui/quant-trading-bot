"""Deterministic Phase 4A diagnostics over checksum-verified migrated inputs.

No downloads, mutations of input data, strategies or claims of vendor accuracy.
Outputs are write-once under ignored runs/, with sealed Phase 2 provenance.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime
import math
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from scipy.integrate import quad
from ..data.storage.provenance import code_revision, digest, file_digest, json_bytes, load_sealed, seal
from .analytics import AnalyticsInputs, ContractMetadata, GREEKS, analyze_observation
from .greeks import bs_greeks
from .pricing import bs_price, solve_iv
from .surface import AnalyticalChain

SAMPLING = '3 per underlying/month/right/DTE-bucket/spot-moneyness/provider-IV-missing stratum, ordered by MD5(contract_id|date) then identity'
LIMITATIONS = [
    'No contemporaneous rate/dividend history or vendor model version retained; strict historical validation is unavailable.',
    'Date-only ACT/365 and quote midpoint are assumptions, not synchronized executable marks.',
    'SPY/QQQ standard American physical contract convention: all local BSM results are European approximations.',
    'Legacy multiplier/style defaults are unverified; unknown settlement is retained, not inferred into source data.',
    'OI remains null; missing provider IV/Greeks stay unavailable. No expired-day IV reconstructed.',
    'Current ThetaData documentation is not proof of the legacy response version or unit normalization.',
    'ATM strike and wing selections are observed approximations; total-variance interpolation is not a calibrated arbitrage-free surface.',
]


def clean_json(value):
    """Convert numerical missingness to JSON null, retaining explicit statuses."""
    if isinstance(value,dict):return {str(k):clean_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean_json(v) for v in value]
    if isinstance(value,(datetime,date,pd.Timestamp)):return value.isoformat()
    if isinstance(value,np.generic):value=value.item()
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def verify_reference(root: Path, ref: dict) -> Path:
    """Resolve only inside the data root and verify exact immutable file bytes."""
    root=Path(root).resolve();p=(root/ref['path']).resolve()
    if not p.is_relative_to(root):raise ValueError('reference escapes data root')
    if file_digest(p)!=ref['sha256']:raise ValueError('source checksum mismatch')
    return p


def stratified_sample(con) -> pd.DataFrame:
    """Bounded deterministic sample of the processed series, including missing IV."""
    return con.sql('''WITH tagged AS (
        SELECT *, date_diff('day',observation_date,expiration) AS dte,
        strftime(observation_date,'%Y-%m') AS sample_month,
        CASE WHEN date_diff('day',observation_date,expiration)=0 THEN '0'
             WHEN date_diff('day',observation_date,expiration)<=7 THEN '1-7'
             WHEN date_diff('day',observation_date,expiration)<=21 THEN '8-21'
             WHEN date_diff('day',observation_date,expiration)<=45 THEN '22-45'
             ELSE 'over45' END AS dte_bucket,
        CASE WHEN underlying_price IS NULL OR underlying_price<=0 THEN 'unknown'
             WHEN abs(strike/underlying_price-1)<=0.01 THEN 'ATM'
             WHEN ("right"='call' AND strike<underlying_price) OR
                  ("right"='put' AND strike>underlying_price) THEN 'ITM' ELSE 'OTM' END AS money_bucket
        FROM processed), numbered AS (
        SELECT *,row_number() OVER (PARTITION BY underlying,sample_month,"right",dte_bucket,
            money_bucket,implied_volatility IS NULL
            ORDER BY md5(contract_id || '|' || CAST(observation_date AS VARCHAR)),contract_id,observation_date) AS sample_rank
        FROM tagged)
        SELECT * FROM numbered WHERE sample_rank<=3
        ORDER BY underlying,sample_month,"right",dte_bucket,money_bucket,contract_id,observation_date
    ''').df()


def comparison_stats(pairs) -> dict:
    """Absolute and relative errors; relative denominator is |provider value|.

    Missing pairs and exactly zero provider denominators are counted separately.
    These are descriptive differences, not correctness/acceptance tolerances.
    """
    pairs=list(pairs)
    valid=[(float(p),float(l)) for p,l in pairs if p is not None and l is not None
           and math.isfinite(p) and math.isfinite(l)]
    absolute=np.array([abs(p-l) for p,l in valid])
    relative=np.array([abs(p-l)/abs(p) for p,l in valid if p!=0])
    def stats(a):
        return dict(mean=float(a.mean()),median=float(np.median(a)),p95=float(np.quantile(a,.95)),
                    maximum=float(a.max())) if len(a) else dict.fromkeys(('mean','median','p95','maximum'))
    return dict(count=len(valid),missing_pair_count=len(pairs)-len(valid),
        relative_count=len(relative),zero_provider_denominator_count=len(valid)-len(relative),
        **{k+'_absolute_difference':v for k,v in stats(absolute).items()},
        **{k+'_relative_difference':v for k,v in stats(relative).items()})


def compare_sample(sample: pd.DataFrame, rate: float, dividend_yield: float):
    """Compare under explicitly supplied scenario inputs, never invented history."""
    details=[]
    for row in sample.to_dict('records'):
        day=pd.Timestamp(row['observation_date']).date()
        multiplier=row.get('multiplier')
        contract=ContractMetadata(row['underlying'],pd.Timestamp(row['expiration']).date(),
            float(row['strike']),row['right'],row.get('exercise_style'),row.get('settlement_type'),
            None if multiplier is None or pd.isna(multiplier) else int(multiplier),
            'legacy_terms_unverified; standard SPY/QQQ convention American/physical')
        inp=AnalyticsInputs(day,rate,dividend_yield,'explicit_constant_scenario_not_historical',
                            'explicit_continuous_yield_scenario_not_historical')
        out=analyze_observation(row,inp,contract)
        out.update(contract_id=row['contract_id'],dte_bucket=row.get('dte_bucket'),
            money_bucket=row.get('money_bucket'),
            quote_timestamp_available=pd.notna(row.get('event_timestamp')),
            underlying_timestamp_available=pd.notna(row.get('underlying_timestamp')))
        details.append(out)
    ivpairs=[(d['provider_iv'],d['local_iv']) for d in details]
    summary=dict(observations=len(details),statuses=dict(Counter(d['status'] for d in details)),
        strict_contemporaneous_validation_count=0,unverifiable_historical_input_count=len(details),
        iv_comparison=comparison_stats(ivpairs),
        missing_provider_iv=sum(d['provider_iv'] is None for d in details),
        unavailable_oi=sum(d['open_interest'] is None for d in details),
        missing_quote_timestamp=sum(not d['quote_timestamp_available'] for d in details),
        missing_underlying_timestamp=sum(not d['underlying_timestamp_available'] for d in details),
        repricing_max_absolute_residual=max((abs(d['repricing_residual']) for d in details
                                            if d['repricing_residual'] is not None),default=None))
    for name in ('reconstructed_iv','provider_iv'):
        local_key='local_greeks' if name=='reconstructed_iv' else 'local_greeks_at_provider_iv'
        summary['greeks_at_'+name]={g:comparison_stats(
            (d['provider_greeks'][g],d[local_key][g]) for d in details) for g in GREEKS}
        # Do not replace raw fields. This separately labelled comparison assumes
        # legacy values followed today's documented unscaled vega/rho convention.
        summary['greeks_at_'+name+'_documented_unit_hypothesis']={g:comparison_stats(
            (None if d['provider_greeks'][g] is None else
             d['provider_greeks'][g]/(100 if g in ('vega','rho') else 1),d[local_key][g])
            for d in details) for g in GREEKS}
    summary['by_underlying']={s:comparison_stats((d['provider_iv'],d['local_iv'])
        for d in details if d['contract']['underlying']==s)
        for s in sorted({d['contract']['underlying'] for d in details})}
    summary['strata_counts']={name:dict(Counter(str(row[name]) for row in sample.to_dict('records')))
        for name in ('underlying','right','dte_bucket','money_bucket','sample_month') if name in sample}
    return summary,details


def numerical_validation() -> dict:
    """Independent payoff integration, parity, round trips and central differences."""
    cases=[]
    fixtures=[(100,100,1,.05,0,.2),(80,100,.5,0,.02,.3),(120,100,2,-.01,.03,.25),
        (100,100,1/365,0,0,.2),(100,100,3,.04,.02,.8),(100,100,.00001,0,0,.01),
        (100,100,1,0,0,.00001)]
    for S,K,T,r,q,sigma in fixtures:
        for right in ('call','put'):
            drift=(r-q-.5*sigma*sigma)*T;width=sigma*math.sqrt(T)
            z=(math.log(K/S)-drift)/width
            def f(x):
                st=S*math.exp(drift+width*x)
                return max(st-K if right=='call' else K-st,0)*math.exp(-x*x/2)/math.sqrt(2*math.pi)
            lo,hi=(max(-12,z),12) if right=='call' else (-12,min(12,z))
            independent=math.exp(-r*T)*quad(f,lo,hi,epsabs=1e-10)[0]
            px=bs_price(S,K,T,r,sigma,right,q);iv=solve_iv(px,S,K,T,r,right,q,tol=1e-10)
            assert abs(px-independent)<2e-8 and iv.status=='ok'
            cases.append(dict(S=S,K=K,T=T,r=r,q=q,sigma=sigma,right=right,
                price=px,independent_price=independent,absolute_error=abs(px-independent),
                recovered_iv=iv.volatility,repricing_residual=iv.residual))
    greek_cases=[]
    for S,K,T,r,q,v in [(100,100,.5,.03,.01,.2),(80,100,2,0,.02,.3),(120,100,1/365,.05,0,.5)]:
        for right in ('call','put'):
            def p(s=S,t=T,vol=v,rate=r):return bs_price(s,K,t,rate,vol,right,q)
            h=.001
            fd=dict(delta=(p(s=S+h)-p(s=S-h))/(2*h),gamma=(p(s=S+h)-2*p()+p(s=S-h))/h**2,
                theta=(p(t=T-1e-6)-p(t=T+1e-6))/(2e-6*365),
                vega=(p(vol=v+1e-5)-p(vol=v-1e-5))/(2e-5*100),
                rho=(p(rate=r+1e-5)-p(rate=r-1e-5))/(2e-5*100))
            g=bs_greeks(S,K,T,r,v,right,q)
            assert all(math.isclose(g[k],fd[k],rel_tol=1e-4,abs_tol=1e-7) for k in g)
            greek_cases.append(dict(S=S,K=K,T=T,r=r,q=q,sigma=v,right=right,
                analytical=g,finite_difference=fd,absolute_errors={k:abs(g[k]-fd[k]) for k in g}))
    return dict(pricing_cases=cases,greek_cases=greek_cases,
        zero_vol_call=bs_price(100,100,1,.05,0),
        zero_vol_expected=100-100*math.exp(-.05),
        invalid_price_status=solve_iv(101,100,100,1,0).status,
        unbracketed_status=solve_iv(bs_price(100,100,1,0,6),100,100,1,0).status,
        expiration_greeks=bs_greeks(100,100,0,0,.2))


def run_validation(root: Path, corpus_manifest: Path, output: Path, *, rate: float,
                   dividend_yield: float, repo: Path) -> dict:
    """Read exact Phase 2 datasets and emit immutable, checksummed report artifacts."""
    root=Path(root).resolve();repo=Path(repo).resolve();output=Path(output).resolve()
    if not output.is_relative_to(repo/'runs'):
        raise ValueError('generated validation output must be under the ignored repository runs area')
    if output.exists():raise FileExistsError('validation output must be new')
    corpus_manifest=Path(corpus_manifest).resolve()
    if not corpus_manifest.is_relative_to(root):raise ValueError('corpus path escapes root')
    m=load_sealed(corpus_manifest)
    before={corpus_manifest:file_digest(corpus_manifest)};paths=[];expected=0;refs=[]
    for part in m['partitions']:
        if part['series']!='processed':continue
        for ref in part['dataset_manifests']:
            p=verify_reference(root,ref);before[p]=file_digest(p);meta=load_sealed(p)
            refs.append(ref);expected+=meta['row_count']
            for file in meta['files']:
                fref={'path':(p.parent/file['path']).relative_to(root).as_posix(),'sha256':file['sha256']}
                f=verify_reference(root,fref);before[f]=file_digest(f);paths.append(str(f))
    if not 0<expected<=2_000_000 or len(paths)>24:
        raise ValueError('unexpected processed corpus size')
    with duckdb.connect() as con:
        con.read_parquet(sorted(paths)).create_view('processed')
        count=con.sql('SELECT count(*) FROM processed').fetchone()[0]
        if count!=expected:raise ValueError('manifest row count mismatch')
        coverage=con.sql("""SELECT underlying,min(observation_date) AS first_date,
            max(observation_date) AS last_date,count(*) AS rows,
            min(date_diff('day',observation_date,expiration)) AS min_dte,
            max(date_diff('day',observation_date,expiration)) AS max_dte,
            count(*) FILTER(WHERE date_diff('day',observation_date,expiration)>45) AS rows_over_45_dte,
            count(*) FILTER(WHERE event_timestamp IS NULL) AS missing_event_timestamp,
            count(*) FILTER(WHERE underlying_timestamp IS NULL) AS missing_underlying_timestamp
            FROM processed GROUP BY underlying ORDER BY underlying""").df().to_dict('records')
        sample=stratified_sample(con)
        summary,details=compare_sample(sample,rate,dividend_yield)
        chains=[]
        for symbol,day in con.sql('SELECT underlying,min(observation_date) FROM processed GROUP BY underlying ORDER BY underlying').fetchall():
            df=con.execute('SELECT * FROM processed WHERE underlying=? AND observation_date=? ORDER BY expiration,strike,"right"',[symbol,day]).df()
            view=AnalyticalChain(df)
            expirations=sorted(df['expiration'].unique())
            positive=[e for e in expirations if pd.Timestamp(e).date()>day]
            selected=sorted(positive,key=lambda e:(abs((pd.Timestamp(e).date()-day).days-30),e))[0]
            chains.append(dict(underlying=symbol,date=str(day),quality=view.quality,
                skew=view.skew(selected),tenors=[view.tenor(t) for t in (7,14,21,30,45,60,90)]))
    numerical=clean_json(numerical_validation())
    for p,sha in before.items():
        if file_digest(p)!=sha:raise ValueError('source changed during validation')
    code_paths=[p for p in (repo/'src/quantbot/options').glob('*.py')]
    code_paths += [repo/'src/quantbot/data/options_loader.py',repo/'src/quantbot/risk/greeks.py',repo/'scripts/validate_phase4a.py']
    code_paths += list((repo/'tests').glob('test_phase4a*.py'))
    code_files={p.relative_to(repo).as_posix():file_digest(p) for p in sorted(code_paths)}
    report=clean_json(dict(phase='4A',version=1,code=code_revision(repo),source_code_sha256=code_files,
        corpus=dict(version=m['corpus_version'],manifest_sha256=file_digest(corpus_manifest),
                    processed_rows=count,partition_count=len(paths),coverage=coverage,datasets=refs),
        assumptions=dict(rate=rate,dividend_yield=dividend_yield,rate_basis='continuous_annual_fraction',
            time_basis='date_only_ACT_365',vendor_unit_hypothesis='raw vega/rho divided by 100; other Greeks as supplied; legacy version unverified'),
        sampling=SAMPLING,comparison=summary,numerical=numerical,chain_examples=chains,
        source_checksums_unchanged=True,limitations=LIMITATIONS))
    details_bytes=json_bytes(clean_json(details))
    report['sample_sha256']=digest(details_bytes)
    report['run_id']='phase4a-'+digest(json_bytes(report))[:16]
    report=seal(report)
    text_report=render_report(report)
    output.mkdir(parents=True)
    files={'observations.json':details_bytes,'report.json':json_bytes(report),
           'report.md':text_report.encode('utf-8')}
    for name,contents in files.items():
        with (output/name).open('xb') as h:h.write(contents)
    manifest=seal(dict(run_id=report['run_id'],code=report['code'],
        corpus=report['corpus'],source_code_sha256=code_files,
        outputs=[dict(path=k,bytes=len(v),sha256=digest(v)) for k,v in files.items()]))
    (output/'manifest.json').write_bytes(json_bytes(manifest))
    return report


def render_report(report: dict) -> str:
    """Full human-readable report with tables and complete diagnostic JSON."""
    s=report['comparison'];n=report['numerical']
    lines=['# Phase 4A validation report','',f"Run: {report['run_id']}",
        f"Code commit: {report['code']['commit']}; dirty: {report['code']['dirty']}.",
        'Exact source hashes and locked dependency identity are in report.json and manifest.json.',
        '',f"Processed corpus: {report['corpus']['processed_rows']:,} records; tested sample: {s['observations']}.",
        '','## Mathematical validation','',
        f"Independent discounted payoff quadrature: {len(n['pricing_cases'])} cases; max error {max(c['absolute_error'] for c in n['pricing_cases']):.12g}.",
        f"Finite-difference Greeks: {len(n['greek_cases'])} cases / 30 comparisons; all tolerances passed.",
        f"Zero-volatility ATM one-year call, S=K=100/r=5%/q=0: {n['zero_vol_call']:.12f}.",
        '', '## Historical diagnostic (not vendor certification)','',
        f"Statuses: {s['statuses']}. Strict contemporaneous historical validations: 0; {s['unverifiable_historical_input_count']} lack required historical assumptions.",
        'Relative differences divide by absolute provider value; zero denominators are excluded and counted.',
        '','| Field / input basis | Pairs | Mean absolute difference | P95 absolute difference | Mean relative difference |',
        '|---|---:|---:|---:|---:|']
    comparisons={'IV':s['iv_comparison']}
    comparisons.update({'Greek at vendor IV / raw '+k:v for k,v in s['greeks_at_provider_iv'].items()})
    comparisons.update({'Greek at vendor IV / documented unit hypothesis '+k:v for k,v in s['greeks_at_provider_iv_documented_unit_hypothesis'].items()})
    for name,v in comparisons.items():
        lines.append(f"| {name} | {v['count']} | {v['mean_absolute_difference']} | {v['p95_absolute_difference']} | {v['mean_relative_difference']} |")
    import json
    for title,key in [('Assumptions','assumptions'),('Historical statistics including failures and strata','comparison'),
                      ('Skew and short-tenor examples','chain_examples'),('Numerical cases','numerical')]:
        lines += ['', '## '+title,'','```json',json.dumps(report[key],indent=2,allow_nan=False),'```']
    lines+=['','## Limitations','']+['- '+x for x in report['limitations']]
    lines+=['','Sources: [ThetaData Greek conventions](https://docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks.html); '
        '[OIC exercise conventions](https://www.optionseducation.org/referencelibrary/faq/options-exercise).',
        'Market observations are retained only in this ignored run directory. No strategy or profitability claim.']
    return '\n'.join(lines)+'\n'
