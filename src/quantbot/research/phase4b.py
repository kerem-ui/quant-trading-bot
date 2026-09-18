"""Frozen, offline Phase 4B research over the bounded Phase 2C corpus.

Generated observations/ledgers stay in ignored runs/. The specification is
user-approved before results and input/code fingerprints are checked again
on completion. No optimization, synthetic historical fills or downloads.
"""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from ..data.storage.provenance import code_revision, digest, file_digest, json_bytes, load_sealed, seal
from ..options.validation import clean_json, verify_reference
from ..options.s05_spec import S05Parameters
from ..options.s05_features import build_signal_panel
from ..options.backtest_engine import OptionsBacktestEngine
from ..options.risk import OptionsRiskLimits
from ..costs.transaction_costs import OptionsCostModel
from ..strategies.s05_implied_vs_realized_vol import S05ImpliedVsRealizedVol


def _text_matches(path, expected):
    data=path.read_bytes()
    # Frozen configuration was recorded on Windows. Git LF/CRLF equivalents
    # are accepted; market-source bytes and all generated outputs are exact.
    lf=data.replace(b'\r\n',b'\n')
    return expected in {digest(data),digest(lf),digest(lf.replace(b'\n',b'\r\n'))}


def load_specification(path: Path, repo: Path):
    """Verify sealed rules and original canonical config/lock before any run."""
    spec=load_sealed(Path(path));repo=Path(repo)
    if spec['format_version']!='phase4b-s05-freeze-v1':raise ValueError('unsupported S05 freeze')
    if not _text_matches(repo/'configs/strategy_configs.json',spec['canonical_configuration_sha256']):
        raise ValueError('canonical configuration changed since approval')
    if not _text_matches(repo/'uv.lock',spec['lock_sha256']):raise ValueError('dependency lock changed')
    p=S05Parameters(**spec['parameters'])
    if asdict(p)!=spec['parameters']:raise ValueError('ineffective frozen parameter')
    return spec,p


def guard_unchanged(pins: dict):
    """Do not certify a run whose source, rules or data changed while executing."""
    for path,expected in pins.items():
        if file_digest(path)!=expected:raise ValueError(f'input changed during run: {Path(path).name}')


def reconcile_result(result):
    """Check equity at every date/event, premiums, trade P&L and costs once."""
    expected=result.initial_capital*(1+result.daily_returns).cumprod()
    if not np.allclose(expected,result.equity_curve,rtol=1e-12,atol=1e-8):
        raise ValueError('daily returns do not reconcile to equity')
    for event in result.event_ledger:
        marked=sum(l['qty']*l['multiplier']*l['mark_price'] for l in event['holdings'])
        if not np.isclose(event['cash']+marked,event['equity'],rtol=1e-12,atol=1e-8):
            raise ValueError('event cash/holdings mismatch')
    for tr in result.trades:
        if not np.isclose(tr.net_entry_cash+tr.net_exit_cash-tr.open_cost-tr.close_cost,
                          tr.realized_pnl,rtol=1e-12,atol=1e-8):raise ValueError('trade premium mismatch')
    if not np.isclose(sum(o['cost'] for o in result.orders),result.total_cost,rtol=1e-12,atol=1e-8):
        raise ValueError('order cost mismatch')
    if not np.isclose(result.initial_capital+sum(t.realized_pnl for t in result.trades),
                      result.equity_curve.iloc[-1],rtol=1e-12,atol=1e-8):raise ValueError('closed ledger P&L mismatch')
    return dict(daily_returns=True,event_balance_sheets=True,trade_premiums=True,costs_once=True,ending_cash=True)


def summarize(result, strategy, features, p):
    """Report actual orders/positions, never potential signals as executed trades."""
    checks=reconcile_result(result)
    eq=result.equity_curve;initial=result.initial_capital
    orders=result.orders;opens=[o for o in orders if o['type']=='open']
    eod={e['date']:e for e in result.event_ledger}
    exposure=[]
    for day in eq.index:
        e=eod[day];held=e['holdings'];equity=e['equity']
        active=[tr for tr in result.trades if tr.fill_open<=day<tr.fill_close]
        exposure.append(dict(date=day,gross_option_mark=sum(abs(l['qty']*l['multiplier']*l['mark_price']) for l in held),
            net_option_mark=sum(l['qty']*l['multiplier']*l['mark_price'] for l in held),
            defined_expiry_loss=sum(abs(tr.max_loss) for tr in active),
            fee_budgeted_defined_loss=sum(abs(tr.max_loss)+tr.open_cost+4*p.per_contract_fee+p.multi_leg_penalty for tr in active),
            reserved_capital=sum(tr.width*100+tr.open_cost+4*p.per_contract_fee+p.multi_leg_penalty for tr in active),equity=equity))
    ex=pd.DataFrame(exposure).set_index('date')
    def drawdown(values,start):
        a=np.r_[start,np.asarray(values)];return float(np.min(a/np.maximum.accumulate(a)-1))
    durations=[(tr.fill_close-tr.fill_open).days for tr in result.trades]
    turnover=sum(l['notional'] for o in orders if o['type']!='expire' for l in o['legs'])/initial
    rejected=dict(Counter(r.stage+':'+r.reason for r in result.rejections))
    chronological=[]
    for period,values in eq.groupby(eq.index.to_period('Q')):
        start_ix=eq.index.get_loc(values.index[0]);start=initial if start_ix==0 else float(eq.iloc[start_ix-1])
        os=[o for o in orders if values.index[0]<=o['fill_date']<=values.index[-1]]
        chronological.append(dict(period=str(period),starting_equity=start,ending_equity=float(values.iloc[-1]),
            net_pnl=float(values.iloc[-1]-start),return_fraction=float(values.iloc[-1]/start-1),
            max_drawdown=drawdown(values,start),entries=sum(o['type']=='open' for o in os),
            completed_trades=sum(values.index[0]<=tr.fill_close<=values.index[-1] for tr in result.trades),
            explicit_costs=sum(o['cost'] for o in os),gross_premium_turnover=sum(l['notional'] for o in os if o['type']!='expire' for l in o['legs'])/initial,
            mean_gross_option_mark_fraction=float((ex.loc[values.index,'gross_option_mark']/values).mean())))
    rv=features.rv.notna();iv=features.iv30.notna();warm=features.percentile.notna()
    summary=dict(starting_equity=initial,ending_equity=float(eq.iloc[-1]),net_pnl=float(eq.iloc[-1]-initial),
        total_return=float(eq.iloc[-1]/initial-1),max_drawdown=drawdown(eq,initial),
        candidate_signal_dates=int(features.signal.sum()),weekly_candidate_structures=sum(d['decision']=='candidate' for d in strategy.decisions),
        decision_counts=dict(Counter(d['decision'] for d in strategy.decisions)),
        executable_entries=len(opens),completed_trades=len(result.trades),rejections=rejected,
        rejected_order_count=len(result.rejections),capacity_limited_orders=0,
        capacity_status='unmodeled quote size; one-lot research convention, not capacity certification',
        explicit_trading_costs=result.total_cost,commissions=sum(o['commission'] for o in orders),
        additional_slippage=sum(o['slippage'] for o in orders),duplicate_spread_charge=0,
        gross_premium_cashflow_turnover=turnover,
        gross_trading_pnl=sum(tr.net_entry_cash+tr.net_exit_cash for tr in result.trades),
        holding_calendar_days=durations,duration_min=min(durations) if durations else None,
        duration_median=float(np.median(durations)) if durations else None,duration_max=max(durations) if durations else None,
        max_defined_expiry_loss=float(ex.defined_expiry_loss.max()),
        max_fee_budgeted_defined_loss=float(ex.fee_budgeted_defined_loss.max()),
        max_reserved_capital=float(ex.reserved_capital.max()),
        average_gross_option_mark_fraction=float((ex.gross_option_mark/eq).mean()),
        max_gross_option_mark_fraction=float((ex.gross_option_mark/eq).max()),
        minimum_net_option_mark_fraction=float((ex.net_option_mark/eq).min()),
        max_net_option_mark_fraction=float((ex.net_option_mark/eq).max()),
        feature_counts=dict(session_slots=len(features),valid_rv=int(rv.sum()),valid_iv30=int(iv.sum()),
                            valid_percentile=int(warm.sum()),missing_iv30=int((~iv).sum()),
                            insufficient_rv=int((~rv).sum()),insufficient_percentile=int((~warm).sum())),
        entry_conditions=[dict(fill_date=o['fill_date'],decision_date=o['decision_date'],gross_credit=o['net_cash'],**o['meta']) for o in opens],
        chronological=chronological,reconciliation=checks,
        research_status='DATA_INSUFFICIENT_IV_HISTORY' if not warm.any() else 'OBSERVED_CORPUS_RESEARCH_DEBUG_ONLY')
    return clean_json(summary),ex


def _source_pins(repo):
    paths=list((repo/'src/quantbot').rglob('*.py'))+list((repo/'tests').glob('test_phase4b*.py'))
    paths += [repo/'scripts/run_phase4b.py',repo/'configs/strategy_configs.json',repo/'uv.lock',repo/'pyproject.toml']
    return {path:file_digest(path) for path in paths}


def run_research(repo: Path, data_root: Path, specification: Path,
                 underlying_sources: Path, output: Path):
    """Run only the frozen bounded dataset; refuse overwrite and input drift."""
    repo=repo.resolve();root=data_root.resolve();output=output.resolve()
    if not output.is_relative_to(repo/'runs/phase4b'):raise ValueError('output must be in ignored runs/phase4b')
    if output.exists():raise FileExistsError('write-once Phase 4B output')
    spec,p=load_specification(specification,repo)
    pins=_source_pins(repo);pins[specification]=file_digest(specification)
    portable_code={path.relative_to(repo).as_posix():digest(path.read_bytes().replace(b'\r\n',b'\n')) for path in pins}
    cm=verify_reference(root,dict(path=spec['corpus']['relative_manifest'],sha256=spec['corpus']['sha256']))
    pins[cm]=file_digest(cm);corpus=load_sealed(cm);paths=[];refs=[];expected=0
    for part in corpus['partitions']:
        if part['series']!='processed':continue
        for ref in part['dataset_manifests']:
            mp=verify_reference(root,ref);pins[mp]=file_digest(mp);meta=load_sealed(mp)
            refs.append(ref);expected+=meta['row_count']
            for f in meta['files']:
                fp=verify_reference(root,dict(path=(mp.parent/f['path']).relative_to(root).as_posix(),sha256=f['sha256']))
                pins[fp]=file_digest(fp);paths.append(str(fp))
    if not 0<expected<=2_000_000 or len(paths)>24:raise ValueError('unexpected corpus size')
    closes={}
    for source in spec['underlying_sources']:
        fp=underlying_sources/source['filename']
        if fp.resolve().parent!=underlying_sources.resolve():raise ValueError('invalid underlying source filename')
        if file_digest(fp)!=source['sha256']:raise ValueError('underlying source checksum mismatch')
        pins[fp]=file_digest(fp)
        frame=pd.read_csv(fp,parse_dates=['date']).set_index('date')
        closes[source['symbol']]=frame.adjusted_close
    output.mkdir(parents=True)
    (output/'specification.json').write_bytes(json_bytes(spec))
    report=dict(run_id=output.name,strategy=spec['strategy'],specification_sha256=spec['manifest_sha256'],
        code=code_revision(repo),source_text_hashes=portable_code,corpus=spec['corpus'],
        dataset_manifests=refs,underlying_sources=spec['underlying_sources'],parameters=spec['parameters'],
        limitations=spec['limitations'],unavailable_universe=['IWM'],results={})
    try:
        with duckdb.connect() as con:
            con.read_parquet(sorted(paths)).create_view('processed')
            if con.sql('select count(*) from processed').fetchone()[0]!=expected:raise ValueError('row count mismatch')
            report['processed_rows']=expected
            for symbol in spec['rules']['universe']:
                print('Preparing frozen causal features:',symbol,flush=True)
                frame=con.execute('''select underlying,observation_date,expiration,strike,"right",bid,ask,
                    implied_volatility,delta,gamma,theta,vega,rho,underlying_price,multiplier,
                    contract_id,open_interest from processed where underlying=?
                    order by observation_date,expiration,strike,"right"''',[symbol]).df()
                if frame.empty:report['results'][symbol]=dict(status='unavailable');continue
                # Decimal strikes are exact source identities; convert only at the
                # engine adapter, matching the existing Phase 1 double-price API.
                frame['strike']=frame.strike.astype(float)
                features=build_signal_panel(frame,closes[symbol],p)
                area=output/symbol;area.mkdir()
                features.to_csv(area/'signals.csv',index=True)
                chain=frame.rename(columns={'observation_date':'date','right':'option_type','multiplier':'contract_multiplier'})
                strategy=S05ImpliedVsRealizedVol(symbol,features,p)
                limits=OptionsRiskLimits(max_loss_per_trade=p.max_loss_dollars,max_credit_per_trade=p.max_credit_dollars,
                    max_width=p.max_width,max_concurrent_positions=p.max_positions,
                    max_portfolio_defined_loss_pct=p.aggregate_risk_fraction,spread_max_pct=p.spread_max_pct)
                model=OptionsCostModel(per_contract_fee=p.per_contract_fee,multi_leg_penalty=p.multi_leg_penalty)
                engine=OptionsBacktestEngine(chain,strategy,initial_capital=p.initial_capital,limits=limits,cost_model=model)
                print('Executing frozen S05:',symbol,flush=True)
                try:result=engine.run()
                except Exception as exc:
                    failure=clean_json(dict(status='INCOMPLETE_NO_CERTIFIED_RESULT',error=str(exc),
                        decisions=strategy.decisions,exit_observations=strategy.exit_observations,
                        events=engine._event_ledger,orders=engine._orders,rejections=[asdict(r) for r in engine._rejections]))
                    (area/'failure.json').write_bytes(json_bytes(failure));raise
                summary,exposure=summarize(result,strategy,features,p)
                report['results'][symbol]=summary
                pd.DataFrame(dict(equity=result.equity_curve,cash=result.cash_curve,net_return=result.daily_returns)).to_csv(area/'equity.csv')
                exposure.to_csv(area/'exposure.csv');result.daily_greeks.to_csv(area/'provider_greeks.csv')
                for name,value in dict(summary=summary,decisions=strategy.decisions,exits=strategy.exit_observations,
                    orders=result.orders,trades=[asdict(tr) for tr in result.trades],rejections=[asdict(r) for r in result.rejections],
                    event_ledger=result.event_ledger).items():
                    (area/(name+'.json')).write_bytes(json_bytes(clean_json(value)))
                print(symbol,summary['executable_entries'],'entries;',summary['net_pnl'],'net P&L',flush=True)
        guard_unchanged(pins)
        report['inputs_verified_unchanged']=True
        (output/'report.json').write_bytes(json_bytes(clean_json(report)))
        (output/'report.md').write_text(render_report(report),encoding='utf-8')
        outputs={f.relative_to(output).as_posix():file_digest(f) for f in sorted(output.rglob('*')) if f.is_file()}
        manifest=seal(dict(run_id=output.name,status='complete',specification_sha256=spec['manifest_sha256'],
            code=report['code'],source_text_hashes=portable_code,corpus=spec['corpus'],dataset_manifests=refs,outputs=outputs))
        (output/'manifest.json').write_bytes(json_bytes(manifest))
    except Exception as exc:
        guard_unchanged(pins)
        (output/'incomplete.json').write_bytes(json_bytes(dict(status='incomplete',error=str(exc),specification_sha256=spec['manifest_sha256'])))
        raise
    return report


def render_report(report):
    """Human-readable metrics and complete machine summary, with no alpha claim."""
    lines=['# Phase 4B bounded S05 research','',f"Run: {report['run_id']}",
        'Observed historical corpus; research/debug only, not OOS, alpha or live readiness.',
        '', '| Symbol | Entries | Completed | Explicit costs | Net P&L | Ending equity | Drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for symbol,r in report['results'].items():
        lines.append(f"| {symbol} | {r['executable_entries']} | {r['completed_trades']} | {r['explicit_trading_costs']:.2f} | {r['net_pnl']:.2f} | {r['ending_equity']:.2f} | {r['max_drawdown']:.6%} |")
    lines+=['','Profit trigger D <= 0.50 C; stop D >= 2.00 C, both gross executable premiums. Fees affect P&L only.',
        'Turnover means absolute executed option-premium cash flow divided by initial capital; it is not underlying turnover.',
        'Exposure uses marked option-premium values and defined expiry loss; provider Greeks retain uncertified units.',
        'No financing/borrow/cash interest or combined strategy portfolio is invented.',
        '','## Full metrics and chronological diagnostics','','```json',json.dumps(clean_json(report['results']),indent=2,allow_nan=False),'```',
        '','## Limitations','']+['- '+v for v in report['limitations']]
    return '\n'.join(lines)+'\n'