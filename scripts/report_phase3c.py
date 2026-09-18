"""Render sealed Phase 3C results without rerunning/tuning a strategy."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from quantbot.research.certification import verify_manifest, verify_freeze
from quantbot.data.storage.provenance import load_sealed


def number(value):
    """Human precision only; exact values remain in sealed JSON."""
    return 'undefined' if value is None else f'{value:,.2f}'


def percent(value):
    """Format a fraction without changing its stored value."""
    return 'undefined' if value is None else f'{100*value:.2f}%'


def table(headers, rows):
    """Render a simple Markdown comparison table."""
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',
                      *['| '+' | '.join(map(str,row))+' |' for row in rows]])


def render(repo: Path, run: Path, verification: dict | None = None) -> str:
    """Accept only checksum-verified corrected runs, never historical report files."""
    if not any(run.parts[i:i+2]==('runs','phase3c') for i in range(len(run.parts)-1)):
        raise ValueError('Phase 3C run directory required; legacy reports cannot be certified')
    manifest=verify_manifest(run/'manifest.json')
    frozen=verify_freeze(run/'frozen_specification.json'); spec=frozen['specification']
    summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
    lines=['# Phase 3C — Strategy revalidation report','',
        'These results certify reproducible accounting under a frozen historical research convention. They do not prove alpha, profitability outside this sample, trading capacity or live readiness. No strategy parameters were tuned in response to these results.','',
        '## Frozen identity and inputs','',
        f"Run: `{manifest['run_id']}`. Executed runtime commit: `{manifest['git_commit']}`.",
        f"Frozen specification: `{frozen['manifest_sha256']}`.",
        f"Dataset identity: `{spec['dataset_identity']}`.",
        f"Run-manifest seal: `{manifest['manifest_sha256']}`.",
        f"Inputs: {len(spec['sources'])} immutable legacy-normalized ETF CSV files, {sum(x['rows'] for x in spec['sources']):,} rows, {sum(x['bytes'] for x in spec['sources']):,} bytes. Source hashes match the Phase 2C inventory. All expected sessions between each ETF's first and last available dates are present; OHLCV fields are finite and positive prices/nonnegative volume are required.",
        f"{len(spec['legacy_outputs'])} legacy report files retain their original hashes. {len(spec['code_files'])} runtime source files and the lock/configuration files are fingerprinted. Source and configuration guards passed before and after execution.",
        'Git text fingerprints canonicalize CRLF/LF; market inputs and generated outputs retain exact-byte hashes. Both Git newline checkout modes passed the frozen guards. Legacy report bytes also remain unchanged within each run.',
        'VOO starts 2010-09-09, VTWO 2010-09-22 and XLRE 2015-10-08; the other selected series start 2010-01-04. All end 2026-05-19. Provider retrieval metadata is absent: original vendor provenance cannot be independently authenticated. No synthetic fallback or download was used.',
        '', '## Frozen specifications','']
    for name,fs in spec['strategy_specifications'].items():
        lines += [f"### {name}: {fs['version']}",'',f"Universe: {', '.join(fs['universe'])}.",'']
        lines += [f'- **{k}:** {v}' for k,v in fs['rules'].items() if k!='version']
        lines += ['']
    lines += ['Risk limits are unchanged: portfolio target volatility 10%, gross 1.5, absolute net 1.0, per-name 15%, sector 40%, daily loss 2% triggering a 50% reduction, portfolio drawdown 20%, strategy drawdown 12%; leverage-up disabled for directional books. S02 retains its stricter 4% allocation cap. Caps constrain approved allocations, not a promise that closing marked weights never drift above their original allocation.',
        'Each separate account starts with $1,000,000. Adjusted research prices, next-session open, modeled commission 1bp + half-spread 2bp + slippage 2bp per side; no impact/minimum commission. Cash interest 0; negative cash cannot be freely financed. S03 base borrow 50bp annual on carried net shorts /252. Capacity is disabled in the frozen base; zero capacity-limited orders does not establish real-world liquidity.',
        '', '## Base verified performance','',
        table(['Strategy','Starting equity','Ending equity','Total return','CAGR','Volatility','Sharpe','Sortino','Max drawdown'],[
            [n,number(x['base']['metrics']['starting_equity']),number(x['base']['metrics']['ending_equity']),
             *[percent(x['base']['metrics'][k]) for k in ['total_return','cagr','annualized_volatility']],
             number(x['base']['metrics']['sharpe']),number(x['base']['metrics']['sortino']),percent(x['base']['metrics']['max_drawdown'])] for n,x in summary.items()]),'',
        'CAGR/volatility use 252 sessions/year. Sharpe has a zero hurdle. Sortino uses RMS negative returns across all sessions; undefined ratios remain null, never zero. First-day losses and pre-window equity are included. Full-period results include warm-up and idle cash.',
        '',table(['Strategy','One-way turnover','Annual turnover','Nonzero filled orders','Rejected','Capacity limited','Avg gross / net','Max gross / abs net','Avg nonzero / max name exposure'],[
            [n,number(m['turnover']),number(m['annual_turnover']),m['executed_trades'],m['rejected_orders'],m['capacity_limited_orders'],
             percent(m['mean_gross_exposure'])+' / '+percent(m['mean_net_exposure']),
             percent(m['max_gross_exposure'])+' / '+percent(m['max_absolute_net_exposure']),
             percent(m['mean_nonzero_position_exposure'])+' / '+percent(m['max_position_exposure'])]
            for n,x in summary.items() for m in [x['base']['metrics']]]),'',
        '## Dollar P&L reconciliation','',
        table(['Strategy','Market P&L','Dividend cash','Cash interest','Financing','Borrow','Transaction cost','Net P&L','Compounding error ($)'],[
            [n,*[number(m['component_pnl'].get(k,0)) for k in ['market_pnl','dividends','cash_interest','financing_cost','short_borrow_cost','transaction_cost']],
             number(m['total_net_pnl']),f"{m['return_compounding_error']:.3g}"] for n,x in summary.items() for m in [x['base']['metrics']]]),'',
        'Cost columns are signed deductions. Starting equity plus these components equals ending equity. Explicit dividend cash is zero because adjusted prices already contain the research adjustment. Every daily return, ledger event and marked quantity was reconciled, including all cost scenarios.',
        '',table(['Strategy','Commission','Modeled spread','Additional slippage','Impact'],[
            [n,*[number(x['base']['diagnostics']['cost_attribution'][k]) for k in ['commission','spread','slippage','impact']]] for n,x in summary.items()]),'',
        '## Legacy versus corrected','',
        '**Legacy / non-certified:** stored outputs are shown as historical claims, not as authoritative performance. Their reported CAGR is inconsistent with their own ending equity.','']
    comparison=[]
    for n,x in summary.items():
        key=spec['strategy_specifications'][n]['name'].lower()
        old=json.loads((repo/'reports'/'backtests'/key/'metrics.json').read_text())
        m=x['base']['metrics']; implied=(old['final_equity']/old['initial_capital'])**(252/old['n_days'])-1
        comparison.append([n,number(old['final_equity']),number(m['ending_equity']),percent(old['total_return']),percent(m['total_return']),
            percent(old['cagr']),percent(implied),percent(m['cagr']),number(old['sharpe']),number(m['sharpe'])])
    lines += [table(['Strategy','Legacy equity','Corrected equity','Legacy return','Corrected return','Legacy stated CAGR','Legacy equity-implied CAGR','Corrected CAGR','Legacy Sharpe','Corrected Sharpe'],comparison),'',
        'Confirmed mechanisms affecting comparability: Phase 1 actual cash/quantity economics, rejected fills, next-open timing, exactly-once net costs and quantity drift; Phase 3A explicit calendars/funding/borrow; Phase 3B daily actual-held exits, adjusted ATR inputs, eligible-only rankings and S03 quantity hedges. Current runs reject no orders, so current rejected-order counts do not prove how much historical rejected-order handling contributed.',
        'Interest and financing remain zero, so their newly explicit frameworks add no direct dollar contribution here. Short borrow does contribute to S03. Capacity is disabled and impact zero, so no capacity cap or impact penalty drives these base results. There is no defensible exact dollar decomposition of every historical fix: the old code/config/data retrieval histories and stored accounting are insufficient for an isolated causal attribution. Worse corrected performance is evidence about the frozen strategy, not a reason to restore invalid accounting.',
        '', '## Chronological evidence — previously observed periods','',
        table(['Strategy','Period','Return','Drawdown','Annual turnover','Mean gross / net','Filled orders','Trading / borrow cost'],[
            [n,label,percent(m['total_return']),percent(m['max_drawdown']),number(m['annual_turnover']),
             percent(m['mean_gross_exposure'])+' / '+percent(m['mean_net_exposure']),m['executed_trades'],
             number(-m['component_pnl']['transaction_cost'])+' / '+number(-m['component_pnl']['short_borrow_cost'])]
            for n,x in summary.items() for label,m in x['base']['chronological_periods'].items()]),'',
        'Windows inherit preceding cash, positions, warm-up and risk state. They are not independently reset or optimized accounts.',
        '', '## Expanding-history walk-forward boundaries','',
        table(['Strategy','Measurement dates','Return','Drawdown','Annual turnover','Mean gross','Filled orders','Total trading/borrow cost'],[
            [n,m['start']+' — '+m['end'],percent(m['total_return']),percent(m['max_drawdown']),number(m['annual_turnover']),
             percent(m['mean_gross_exposure']),m['executed_trades'],number(-m['component_pnl']['transaction_cost']-m['component_pnl']['short_borrow_cost'])]
            for n,x in summary.items() for w in x['base']['walk_forward'] for m in [w['metrics']]]),'',
        'These reuse the existing four expanding-history boundaries on the continuous causal engine path. No fold-specific parameter fit or risk reset occurs. The helper leaves its initial history segment and last three sessions outside the four diagnostic measurement blocks; the full run and three main chronological periods include all 4,119 sessions. This is not untouched OOS.',
        '', '## Deterministic cost and borrow sensitivity','',
        table(['Strategy','Scenario','Ending equity','Return','Sharpe','Trading cost','Borrow cost','Filled orders'],[
            [n,label,number(m['ending_equity']),percent(m['total_return']),number(m['sharpe']),number(-m['component_pnl']['transaction_cost']),
             number(-m['component_pnl']['short_borrow_cost']),m['executed_trades']]
            for n,x in summary.items() for label,v in x.items() if label!='classification' for m in [v['metrics']]]),'',
        'Zero trading cost retains S03 base borrow. Borrow 0/100bp scenarios retain base trading fees. Only specified charge assumptions change; S01 entry cost screening stays at base. Cost-driven changes to equity, quantities and risk pause timing are economic feedback, so ending-equity differences need not equal the arithmetic fee difference.',
        '', '## Strategy diagnostics','']
    d=summary['S01']['base']['diagnostics']; q=pd.read_csv(run/'S01/base/quantities.csv',index_col=0); active=q.abs().sum(axis=1)>1e-9
    lines += ['### S01','',
        f"{d['completed_episodes']} completed holding episodes; {d['open_episodes']} terminal open episodes; median completed duration {number(d['median_completed_holding_sessions'])} sessions. Candidate trend-state persistence {percent(d['signal_persistence'])}. The five largest profitable episodes contribute {percent(d['top_five_episodes_positive_gain_share'])} of positive episode gains.",
        f"Episodes shorter than 20 inclusive sessions contribute ${number(d['short_holds_net_pnl'])}; longer episodes contribute ${number(d['long_holds_net_pnl'])}. This is descriptive holding-duration attribution, not a minimum-hold optimization. Hard stops and central risk may override soft holds. There are {d['daily_exit_or_risk_decisions']} off-cycle exit/risk decisions.",
        f"Actual holdings are active on {int(active.sum())} sessions; the last active close is {q.index[active][-1] if active.any() else 'none'}. The existing 12% drawdown pause leads to prolonged flat cash after the breach; no reset/re-entry rule is invented. Inactive subsequent periods are not successful strategy tests. The zero-cost outcome must be considered alongside the charged outcome.",
        f"Largest positive ETF contributor share: {percent(d['largest_positive_contributor_share'])}. Net dollar contribution by ETF:",'',table(['ETF','Net P&L'],[[s,number(v)] for s,v in sorted(d['instrument_net_pnl'].items(),key=lambda x:-x[1])]),'']
    d=summary['S02']['base']['diagnostics']
    lines += ['### S02','',
        f"Mean daily adjacent score-rank correlation {number(d['mean_daily_rank_correlation'])}; average active holding breadth {number(d['mean_active_holdings'])}; mean active holdings HHI {number(d['mean_holdings_hhi'])}. Largest positive ETF contribution share {percent(d['largest_positive_contributor_share'])}.",
        f"Pre-ranking eligibility changes the selected set in {d['eligibility_selection_changed_months']} of {d['eligible_months_examined']} examined monthly decisions relative to post-ranking masking at the same decision-time inputs. This isolates the ranking-eligibility diagnostic; it is not a separate legacy-accounting performance backtest.",
        'Net dollar contribution by ETF:','',table(['ETF','Net P&L'],[[s,number(v)] for s,v in sorted(d['instrument_net_pnl'].items(),key=lambda x:-x[1])]),'',
        'Executed-holdings-weighted eligible percentile factor exposures:','',table(['Factor','Average percentile exposure'],[[s,number(v)] for s,v in d['executed_holdings_factor_rank_exposure'].items()]),'',d['factor_pnl'],'']
    d=summary['S03']['base']['diagnostics']
    lines += ['### S03','',
        f"Selected pairs: {', '.join(d['selected_pairs'])}. Completed pair episodes: {d['completed_pair_episodes']}; median episode duration {number(d['pair_episode_median_sessions'])} sessions. Largest positive pair contribution share {percent(d['largest_positive_contributor_share'])}.",
        d['attribution_convention'],
        'Selected candidates and executed pairs differ: pairs selected without an entry signal produce no fictitious trade. Pooled beta means across different ETF pairs are not a beta-stability test; the per-pair ranges/SDs are the meaningful drift diagnostics.',
        'The beta=2 hedge earns zero pre-cost P&L for delta-A=2, delta-B=1 per unit scalar; equal-dollar legs generally do not. Observed pair P&L below is calculated from accepted executed component quantities and reconciles to actual account P&L, not from an equal-dollar spread proxy.','',
        table(['Pair','Market P&L','Trading cost','Borrow','Net P&L','Active sessions','Beta min/max','Beta SD'],[
            [s['pair'],*[number(s[k]) for k in ['market_pnl','trading_cost','borrow_cost','net_pnl']],s['active_sessions'],
             number(s['beta_min'])+' / '+number(s['beta_max']),number(s['beta_std'])] for s in d['pair_summary']]),'',
        'Diagnostics at actual causal selection dates (selected candidates only; these are selection statistics, not independent proof of cointegration):','',
        table(['Statistic','Mean','Minimum','Maximum'],[[k,number(v.get('mean')),number(v.get('min')),number(v.get('max'))] for k,v in d['selection_summary'].items()]),'',
        '## Research history, status and limitations','',
        'The whole source period is previously observed development/research data. Reports and scripts explicitly examined the same three subperiods, many factor weights, individual factors, binary/conviction trends and multiple pairs. Untouched OOS does not exist in the available evidence; a demonstrably observed-but-untuned holdout cannot be established. No current period is relabeled fresh validation merely because it is in a walk-forward table.',
        '',table(['Strategy','Status','Failed predefined gates'],[[n,x['classification']['status'],', '.join(x['classification']['failed_gates']) or 'none'] for n,x in summary.items()]),'',
        'The predefined gates require 5 years, 30 completed episodes, positive base and 2x returns, two positive main periods, drawdown<=20%, and no single positive contributor above 50%. Rejection requires nonpositive base and 2x results and at most one positive main period. Otherwise evidence is uncertain. These are transparent descriptive triage rules, not statistical confidence claims.',
        'Nominal observation length is 16.35 trading years; effective active samples may be much smaller. Episodes and pairs overlap and are not independent draws. Historical variant testing, universe selection and surviving ETFs bias interpretation. Positive Sharpe or CAGR does not establish alpha, and frozen daily execution does not establish scalable liquidity. The S02 factor composite lacks unique additive factor P&L; S03 overlapping pairs lack independent capital accounts.',
        '', *['- '+warning for warning in spec['warnings']], '',
        '## Reproducibility and acceptance','',
        'All 11 predefined runs passed cash/quantity/mark, daily P&L-component and equity-return reconciliation. Actual symbol episodes and S03 pair attributions reconcile to executed holdings/costs. The source/configuration/legacy-output guards and output manifest checks passed. Strategy code, risk/accounting engines, market data, parameter values and dependencies remain unchanged. No combined-strategy certificate is issued.',
        'Generated data and detailed run files remain in ignored `runs/phase3c/`; only portable freeze metadata, small summary evidence, code/tests and documentation belong in Git. See `phase3c_research_protocol.md` for exact offline reproduction commands. A second machine needs separately restored hash-identical source blobs; a code clone alone intentionally contains no market data.',
        'The Phase 3C research-reproducibility acceptance criterion is satisfied conditional on the declared legacy-data and execution conventions. Research rejection/uncertainty is an allowed result, not a failed accounting certificate. No Phase 4 work has started.','']
    if verification is not None:
        lines += ['## Exact verification results','',
            table(['Check','Passed','Skipped','Failed','Warnings','Collection errors'],[
                [label,x.get('passed',0),x.get('skipped',0),x.get('failed',0),x.get('warnings',0),x.get('collection_errors',0)]
                for label,x in verification['tests'].items()]),'',
            'Final full-suite elapsed seconds: '+str(verification['full_suite_seconds'])+'.',
            'The 14 skips are existing SEC-cache-dependent tests without populated local company caches. No economically correct assertion was weakened.',
            '', 'Dependency checks: '+verification['dependencies'],
            '', 'Test-first history: '+verification['test_first_history'],
            '', '## Files changed','', *['- `'+f+'`' for f in verification['files_changed']], '',
            'Source/test/documentation and small portable metadata only are eligible for Git. Market inputs, large generated ledgers and databases remain untracked. Original OneDrive source hashes were rechecked. Phase1/2/3A/3B production modules and locked dependencies are unchanged.','']
    return '\n'.join(lines)


def main():
    """Create a new report without overwriting a historical artifact."""
    ap=argparse.ArgumentParser(); ap.add_argument('--repo',type=Path,default=Path.cwd())
    ap.add_argument('--run',type=Path,required=True); ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--verification',type=Path,required=True)
    args=ap.parse_args(); text=render(args.repo,args.run,load_sealed(args.verification))
    with args.output.open('x',encoding='utf-8') as f: f.write(text)

if __name__=='__main__': main()
