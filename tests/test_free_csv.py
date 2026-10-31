"""Synthetic fixtures only. No scraped or licensed data is bundled here."""
from __future__ import annotations
import csv
import io
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keiba_backtest.free_csv import import_free_csv, score_free_csv, inspect_csv
from keiba_backtest.cli import main


class TestOfflineFreeCSV(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)
        self.odds=self.dir/'odds.csv'
        self.roster=self.dir/'results.csv'
        self.map=self.dir/'map.json'
        self.db=self.dir/'private.sqlite3'
        self.source='https://www.kaggle.com/datasets/example/synthetic'
        self.mapping={'odds':{'race_id':'Race','number':'Horse','odds':'単勝'},
                      'roster':{'race_id':'Race','number':'Horse','finish':'着順'}}
        self.map.write_text(json.dumps(self.mapping,ensure_ascii=False))
        self.write_csv(self.odds, ['Race','Horse','単勝'],[
            ['TEST_A','1','2.0'], ['TEST_A','2','3.0'], ['TEST_A','3','6.0'],
            ['TEST_B','1','9.0'], ['TEST_B','2','2.0'], ['TEST_B','3','---'],
            ['TEST_C','1','5.0'], ['TEST_C','2','5.0'], ['TEST_C','3','5.0'],
        ])
        self.write_csv(self.roster,['Race','Horse','着順'],[
            ['TEST_A','1','2'],['TEST_A','2','1'],['TEST_A','3','3'],
            ['TEST_B','1','1'],['TEST_B','2','2'],['TEST_B','3','3'],
            ['TEST_C','1','1'],['TEST_C','2','1'],['TEST_C','3','3'],
        ])

    @staticmethod
    def write_csv(path, headers, rows,encoding='utf-8-sig'):
        with path.open('w',newline='',encoding=encoding) as f:
            writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows)

    def ingest(self,**overrides):
        args={'odds_csv':self.odds,'roster_csv':self.roster,'db':self.db,
              'mapping_file':self.map,'source_url':self.source}
        args.update(overrides)
        return import_free_csv(**args)

    def test_header_inspection_and_encoding(self):
        self.assertEqual(inspect_csv(self.odds)['columns'],['Race','Horse','単勝'])
        cp=self.dir/'sjis.csv'
        self.write_csv(cp,['race_id','馬番','単勝'],[['S','1','3.2']],encoding='cp932')
        self.assertEqual(inspect_csv(cp,encoding='cp932')['columns'],['race_id','馬番','単勝'])

    def test_scoring_complete_only_and_baselines(self):
        result=self.ingest()
        self.assertEqual(result['odds_rows'],9)
        self.assertEqual(result['roster_rows'],9)
        self.assertEqual(result['odds_races'],3)
        self.assertFalse(result['market_is_pre_race_quote'])
        report=score_free_csv(db=self.db,import_id=result['import_id'])
        self.assertEqual(report['scored_races'],1)
        self.assertEqual(report['skipped_by_reason'],{'missing_prices':1,'not_exactly_one_winner':1})
        # 1/3 divided by (1/2+1/3+1/6) == 1/3.
        self.assertAlmostEqual(report['mean_scores']['model_market_log_loss'],-math.log(1/3))
        self.assertAlmostEqual(report['mean_scores']['uniform_log_loss'],math.log(3))
        self.assertEqual(report['market_vs_archived_model'],'not_available_without_archived_asof_forecasts')
        self.assertTrue(report['not_a_purchase_backtest'])
        with closing(sqlite3.connect(self.db)) as con:
            meta=con.execute('select provenance,authorisation_to_redistribute from csv_imports').fetchone()
        self.assertEqual(meta,('RETROSPECTIVE_CSV_SELF_REPORTED_NOT_SOURCE_VERIFIED',0))

    def test_no_roster_no_certified_market_scores(self):
        self.map.write_text(json.dumps({'odds':self.mapping['odds']},ensure_ascii=False))
        result=self.ingest(roster_csv=None)
        report=score_free_csv(db=self.db,import_id=result['import_id'])
        self.assertEqual(report['scored_races'],0)
        self.assertEqual(report['skipped_by_reason']['no_complete_result_roster'],3)
        self.assertIsNone(report['mean_scores'])

    def test_duplicate_rows_rollback(self):
        with self.odds.open('a',encoding='utf-8') as f:
            f.write('TEST_A,2,9.0\n')
        with self.assertRaisesRegex(ValueError,'duplicate odds row'):
            self.ingest()
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute('select count(*) from csv_imports').fetchone()[0],0)
            self.assertEqual(con.execute('select count(*) from csv_win_odds').fetchone()[0],0)

    def test_duplicate_import_blocked(self):
        record=self.ingest()
        with self.assertRaisesRegex(ValueError,'already recorded'):
            self.ingest()
        self.assertEqual(score_free_csv(db=self.db,import_id=record['import_id'])['scored_races'],1)

    def test_missing_odds_col_and_unparsable_values(self):
        self.mapping['odds']['odds']='bad_col'
        self.map.write_text(json.dumps(self.mapping,ensure_ascii=False))
        with self.assertRaisesRegex(ValueError,'columns not found'):
            self.ingest()
        self.mapping['odds']['odds']='単勝'
        self.map.write_text(json.dumps(self.mapping,ensure_ascii=False))
        self.odds.write_text('Race,Horse,単勝\nTEST_A,1,abc\n')
        with self.assertRaisesRegex(ValueError,'unrecognised win odds'):
            self.ingest()

    def test_mismatch_declines_to_score(self):
        rows=[['TEST_A','1','2'],['TEST_A','2','1'],['TEST_A','4','3']]
        self.write_csv(self.roster,['Race','Horse','着順'],rows)
        result=self.ingest()
        r=score_free_csv(db=self.db,import_id=result['import_id'])
        self.assertEqual(r['scored_races'],0)
        self.assertEqual(r['skipped_by_reason']['incomplete_odds_or_roster_mismatch'],1)

    def test_invalid_source_and_mapping(self):
        with self.assertRaisesRegex(ValueError,'HTTPS'):
            self.ingest(source_url='http://example.com')
        with self.assertRaisesRegex(ValueError,'HTTPS'):
            self.ingest(source_url='https://u:p@example.com/abc')
        self.map.write_text('{}')
        with self.assertRaisesRegex(ValueError,'sections must exactly match'):
            self.ingest()

    def test_cli_inspect_import_and_score(self):
        capture=io.StringIO()
        with redirect_stdout(capture):
            main(['inspect-free-csv','--input',str(self.odds)])
        self.assertIn('"Race"',capture.getvalue())
        report_path=self.dir/'report.json'
        with redirect_stdout(io.StringIO()):
            main(['import-free-csv','--odds-csv',str(self.odds), '--roster-csv',str(self.roster),
                  '--mapping',str(self.map),'--source-url',self.source,'--db',str(self.db),
                  '--output',str(report_path)])
        manifest=json.loads(report_path.read_text())
        scored_file=self.dir/'score.json'
        with redirect_stdout(io.StringIO()):
            main(['score-free-csv','--db',str(self.db),'--import-id',manifest['import_id'],
                  '--output',str(scored_file)])
        self.assertEqual(json.loads(scored_file.read_text())['scored_races'],1)


if __name__=='__main__':
    unittest.main()
