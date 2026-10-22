import copy
import hashlib
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.institutional_review import DailyTurnoverSnapshot,liquidity_history
from scripts.research_work_queue import build_queue
from scripts.run_research_pipeline import ROOT,research_stages,run_pipeline
from tw_model_v880.contracts import OBLIGATIONS
from tw_model_v880.evidence import GATES


ASOF='2026-10-22T12:00:00+08:00'


class SharedLiquiditySources(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.prices=self.root/'prices';self.prices.mkdir()
        self.bars=[dict(market='TWSE',code=code,date='2026-10-21',turnover_ntd=100+i)
                   for i,code in enumerate(('6206','9802'))]
        self.daily=self.prices/'2026-10-21.json'
        self.write_daily()
        for code in ('6206','9802'):
            path=self.prices/'issuer_history/TWSE'/(code+'.json')
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(dict(issuer=code,market='TWSE',by_month={
                '202610':dict(captured_at_utc='2026-10-21T12:00:00+00:00',rows=[
                    dict(date=f'2026-10-{d:02d}',turnover_ntd=80+d) for d in range(1,20)])})))

    def write_daily(self):
        raw=json.dumps(self.bars).encode();self.daily.write_bytes(raw)
        (self.prices/'latest_manifest.json').write_text(json.dumps(dict(
            date=self.daily.stem,normalized_sha256=hashlib.sha256(raw).hexdigest())))

    def row(self,code='6206',day='2026-10-21'):
        return dict(market='TWSE',code=code,price_date=day)

    def test_one_market_read_serves_multiple_issuers_with_identical_results(self):
        expected=[liquidity_history(self.root,self.row(code),ASOF) for code in ('6206','9802')]
        original=Path.read_bytes
        reads=[]
        def measured(path):
            if path==self.daily:reads.append(path)
            return original(path)
        with patch.object(Path,'read_bytes',measured):
            snapshot=DailyTurnoverSnapshot(self.root,ASOF,'2026-10-21')
            actual=[liquidity_history(self.root,self.row(code),ASOF,snapshot) for code in ('6206','9802')]
        self.assertEqual(actual,expected)
        self.assertEqual(len(reads),1)
        self.assertEqual(actual[0]['sessions'],20)
        self.assertFalse(actual[0]['spread_and_exit_verified'])

    def test_next_report_rereads_revisions_and_rejects_changed_bytes(self):
        snapshot=DailyTurnoverSnapshot(self.root,ASOF,'2026-10-21')
        prior=liquidity_history(self.root,self.row(),ASOF,snapshot)
        self.bars[0]['turnover_ntd']=1;self.daily.write_text(json.dumps(self.bars))
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            liquidity_history(self.root,self.row(),ASOF)
        self.write_daily()
        current=liquidity_history(self.root,self.row(),ASOF)
        self.assertNotEqual(prior,current)

    def test_future_session_and_capture_are_not_added_to_earlier_window(self):
        (self.prices/'2026-10-23.json').write_text('invalid future data')
        snapshot=DailyTurnoverSnapshot(self.root,ASOF,'2026-10-21')
        older=liquidity_history(self.root,self.row(day='2026-10-19'),ASOF,snapshot)
        self.assertEqual(older['sessions'],19)
        self.assertEqual(snapshot.daily_files_read,1)
        historical=liquidity_history(self.root,self.row(),'2026-10-20T12:00:00+08:00')
        self.assertEqual(historical['sessions'],0)

    def test_bad_latest_hash_does_not_reject_an_older_issuer_window(self):
        self.daily.write_bytes(b'tampered')
        snapshot=DailyTurnoverSnapshot(self.root,ASOF,'2026-10-21')
        self.assertEqual(liquidity_history(self.root,self.row(day='2026-10-19'),ASOF,snapshot)['sessions'],19)
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            liquidity_history(self.root,self.row(),ASOF,snapshot)

    def test_conflicting_turnover_and_wrong_dates_still_reject(self):
        self.bars[0]['date']='2026-10-20';self.write_daily()
        snapshot=DailyTurnoverSnapshot(self.root,ASOF,'2026-10-21')
        with self.assertRaisesRegex(ValueError,'DATE_MISMATCH'):
            liquidity_history(self.root,self.row(),ASOF,snapshot)
        self.assertEqual(liquidity_history(self.root,self.row('9802'),ASOF,snapshot)['sessions'],20)
        self.bars[0]['date']='2026-10-21';self.write_daily()
        path=self.prices/'issuer_history/TWSE/6206.json'
        obj=json.loads(path.read_text())
        obj['by_month']['202610']['rows'].append(dict(date='2026-10-21',turnover_ntd=999))
        path.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError,'CONFLICTING'):
            liquidity_history(self.root,self.row(),ASOF)

    def test_cannot_reuse_snapshot_for_different_cutoff_or_root(self):
        snapshot=DailyTurnoverSnapshot(self.root,ASOF,'2026-10-21')
        with self.assertRaisesRegex(ValueError,'CONTEXT_MISMATCH'):
            liquidity_history(self.root,self.row(),'2026-10-23T12:00:00+08:00',snapshot)


class PipelineTiming(unittest.TestCase):
    def test_core_defers_expensive_observation_until_after_vintage_freeze(self):
        core=research_stages('core');observation=research_stages('observation')
        self.assertEqual(core+observation,research_stages())
        self.assertEqual([name for name,_ in observation],['shadow_comparison','benchmark_validation','institutional_review'])
        self.assertFalse(set(name for name,_ in core)&set(name for name,_ in observation))
        self.assertIn(('historical_source_readiness',['historical_pit_readiness.py']),core)

    def test_records_measured_stages_in_order(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);calls=[]
            def runner(argv,**kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv,0)
            clock=iter(range(30)).__next__
            report=run_pipeline(root,runner=runner,clock=clock,
                                stages=[('one',['first.py']),('two',['second.py','--flag'])])
            self.assertEqual(report['status'],'SUCCESS')
            self.assertEqual([s['stage'] for s in report['stages']],['one','two'])
            self.assertTrue(all(s['elapsed_seconds']>0 for s in report['stages']))
            self.assertEqual(calls[1][-1],'--flag')
            self.assertTrue(report['engineering_timing_is_not_investment_validation'])

    def test_failure_is_saved_and_later_stages_never_execute(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);calls=[]
            def runner(argv,**kwargs):
                calls.append(argv)
                raise subprocess.CalledProcessError(7,argv)
            with self.assertRaises(subprocess.CalledProcessError):
                run_pipeline(root,runner=runner,stages=[('bad',['bad.py']),('later',['later.py'])])
            report=json.loads((root/'tw-market-data/rankings/latest_pipeline_timing.json').read_text())
            self.assertEqual(report['failed_stage'],'bad')
            self.assertEqual(report['stages'][0]['returncode'],7)
            self.assertEqual(len(calls),1)


class EvidenceQueue(unittest.TestCase):
    def inputs(self):
        research=dict(model='TEST',estimate_vintage=ASOF,asof_price_date='2026-10-21',
                      model_code_sha256='a'*64,target_date='2027-12-31')
        def issuer(code,passed=()):
            gates={name:dict(stage='FORMAL_PASS' if name in passed else 'MIRROR_CAPTURED',
                             decision='PASS' if name in passed else 'PENDING',formal_pass=name in passed,
                             scope=OBLIGATIONS[name][0],required_evidence=OBLIGATIONS[name][1],
                             invalidates_on=OBLIGATIONS[name][2],reason='TEST SOURCE MISSING') for name in GATES}
            return dict(code=code,market='TWSE',financial_period='2026-Q2',formal_Aplus=False,
                        research_upside_pct=50,gate_stage=gates)
        progress={k:research[k] for k in ('model','estimate_vintage','asof_price_date')}
        progress['issuer_diagnostics']=[issuer('1111',GATES[:3]),issuer('9802'),issuer('2222')]
        return progress,research

    def test_prioritizes_focus_then_completed_evidence_without_issuing_passes(self):
        progress,research=self.inputs();before=copy.deepcopy(progress)
        report=build_queue(progress,research)
        self.assertEqual([r['code'] for r in report['issuer_jobs']],['9802','1111','2222'])
        self.assertEqual(report['unresolved_gate_count'],36)
        self.assertEqual(report['certificates_issued'],0)
        self.assertEqual(progress,before)
        self.assertTrue(report['shared_strategy_collection_task']['per_issuer_and_subgroup_applicability_review_required'])
        self.assertEqual(len(report['shared_strategy_collection_task']['affected_issuers']),3)

    def test_rejects_stale_report_missing_gates_and_inconsistent_pass(self):
        progress,research=self.inputs()
        with self.assertRaisesRegex(ValueError,'CONTEXT_MISMATCH'):
            build_queue(dict(progress,estimate_vintage='OLD'),research)
        del progress['issuer_diagnostics'][0]['gate_stage'][GATES[0]]
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_GATE'):
            build_queue(progress,research)
        progress,research=self.inputs()
        progress['issuer_diagnostics'][1]['gate_stage'][GATES[0]]['formal_pass']=True
        with self.assertRaisesRegex(ValueError,'INCONSISTENT_FORMAL_PASS'):
            build_queue(progress,research)


class PublicationRace(unittest.TestCase):
    def git(self,where,*args):
        return subprocess.run(['git',*args],cwd=where,check=True,capture_output=True,text=True).stdout.strip()

    def run_publication(self,remote_moved):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);remote=root/'remote.git';writer=root/'writer';worker=root/'worker'
            self.git(root,'init','--bare','--initial-branch=main',str(remote))
            self.git(root,'clone',str(remote),str(writer))
            self.git(writer,'config','user.name','Test');self.git(writer,'config','user.email','test@example.invalid')
            data=writer/'tw-market-data'
            for folder in ('evidence/v880','rankings','pit_vintages','experiments','benchmarks'):
                path=data/folder;path.mkdir(parents=True,exist_ok=True);(path/'seed').write_text('seed')
            (writer/'source.txt').write_text('original')
            self.git(writer,'add','.');self.git(writer,'commit','-m','seed');self.git(writer,'push','origin','main')
            self.git(root,'clone',str(remote),str(worker))
            output=worker/'tw-market-data/rankings/output.txt';output.write_text('validated initial result')
            if remote_moved:
                (writer/'source.txt').write_text('new source')
                self.git(writer,'add','.');self.git(writer,'commit','-m','concurrent data');self.git(writer,'push','origin','main')
            fakebin=root/'bin';fakebin.mkdir();log=root/'calls.txt'
            python=fakebin/'python'
            python.write_text('#!/bin/sh\n'+'printf "%s\\n" "$*" >> "$PIPELINE_TEST_LOG"\n'+
                              'if [ "$1" = "scripts/run_research_pipeline.py" ] && [ "$3" = "core" ]; then\n'+
                              '  cp source.txt tw-market-data/rankings/output.txt\nfi\n')
            python.chmod(0o755)
            workflow=(ROOT/'.github/workflows/tw_v877_research_rank.yml').read_text()
            body=workflow.split('      - name: Save current results on main only',1)[1].split('        run: |\n',1)[1]
            body=body.split('      - name:',1)[0]
            env=dict(os.environ,PATH=str(fakebin)+os.pathsep+os.environ['PATH'],PIPELINE_TEST_LOG=str(log))
            subprocess.run(['bash','-e','-o','pipefail','-c',textwrap.dedent(body)],cwd=worker,env=env,
                           capture_output=True,text=True,check=True)
            calls=log.read_text()
            self.assertEqual(calls.count('scripts/run_research_pipeline.py --phase core'),int(remote_moved))
            self.assertEqual(calls.count('scripts/run_research_pipeline.py --phase observation'),1)
            self.assertEqual(output.read_text(),'new source' if remote_moved else 'validated initial result')
            self.assertEqual(self.git(worker,'rev-parse','HEAD'),self.git(remote,'rev-parse','main'))

    def test_unchanged_main_publishes_existing_outputs_without_second_pipeline(self):
        self.run_publication(False)

    def test_concurrent_main_update_forces_rebuild_before_publication(self):
        self.run_publication(True)


if __name__=='__main__':
    unittest.main()
