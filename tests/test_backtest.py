import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keiba_backtest.probability import model_probabilities, scenario_subset
from keiba_backtest.records import (forecast_from_legacy, load_json, validate_forecast,
                                    validate_outcome, validate_market)
from keiba_backtest.scoring import (loss, market_probabilities, power_calibrate,
                                    score_forecast, uniform_probabilities)
from keiba_backtest.temporal import walk_forward, fit_exponent


class TestBacktest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = load_json(ROOT/'data/2026_kikka_original_model_inputs.json')
        cls.forecast = load_json(ROOT/'data/forecasts/2026_kikka_forecast.json')
        cls.result = load_json(ROOT/'data/outcomes/2026_kikka_result.json')

    def test_sha_source_frozen_and_reconstruct(self):
        doc = (ROOT/'archive/2026_kikka_sho_report.md').read_bytes()
        model = (ROOT/'data/2026_kikka_original_model_inputs.json').read_bytes()
        self.assertEqual(hashlib.sha256(doc).hexdigest(),self.forecast['original_model_sha256'])
        self.assertEqual(hashlib.sha256(model).hexdigest(),self.forecast['model_inputs_sha256'])
        recreated = forecast_from_legacy(self.inputs,self.forecast['race_id'],
                                         self.forecast['race_at'],self.forecast['asof'],
                                         self.forecast['origin_source'],self.forecast['original_model_sha256'])
        # Stable identifiers must be exact; binary float accumulation can vary
        # by a few ULPs across supported Python versions.
        self.assertEqual(len(recreated['runners']), len(self.forecast['runners']))
        for actual, expected in zip(recreated['runners'], self.forecast['runners']):
            self.assertEqual(actual['number'], expected['number'])
            self.assertEqual(actual['name'], expected['name'])
            for key in ('win_probability', 'top2_probability', 'top3_probability'):
                self.assertAlmostEqual(actual[key], expected[key], delta=1e-12)

    def test_reproduce_original_predictions(self):
        p = model_probabilities(self.inputs)
        self.assertAlmostEqual(sum(p['win']),1,places=10)
        self.assertAlmostEqual(sum(p['top2']),2,places=10)
        self.assertAlmostEqual(sum(p['top3']),3,places=10)
        self.assertAlmostEqual(p['win'][7],.369284861,places=6)
        self.assertAlmostEqual(p['win'][8],.0615261331388629,places=12)
        self.assertAlmostEqual(p['win'][9],.117076,places=5)
        self.assertTrue(all(0<=a<=b<=c<=1.000000001 for a,b,c in zip(p['win'],p['top2'],p['top3'])))

    def test_official_outcome_and_scores(self):
        s = score_forecast(self.forecast,self.result)
        self.assertEqual(s['winner_number'],9)
        self.assertEqual(s['n_runners'],18)
        self.assertAlmostEqual(s['model']['log_loss'],2.78829326533926,places=10)
        self.assertAlmostEqual(s['model']['brier_multiclass_sum'],1.05838802615119,places=10)
        self.assertAlmostEqual(s['uniform']['log_loss'],2.89037175789616,places=10)
        self.assertAlmostEqual(s['uniform']['brier_multiclass_sum'],.94444444444,places=10)

    def test_scenario_diagnostic_not_a_new_forecast(self):
        d = self.inputs
        dry = model_probabilities(d,scenarios=scenario_subset(d,'dry'))['win']
        wet = model_probabilities(d,scenarios=scenario_subset(d,'wet'))['win']
        self.assertAlmostEqual(dry[8],.083718,places=4)
        self.assertAlmostEqual(.4*dry[8]+.6*wet[8],self.forecast['runners'][8]['win_probability'],places=11)

    def test_lookahead_feature_rejected(self):
        f = copy.deepcopy(self.forecast)
        f['features']=[{'name':'actual_ground','available_at':'2026-10-25T16:00:00+09:00'}]
        with self.assertRaisesRegex(ValueError,'lookahead'):
            validate_forecast(f)

    def test_post_race_forecast_rejected(self):
        f = copy.deepcopy(self.forecast)
        f['asof']='2026-10-25T16:00:00+09:00'
        with self.assertRaisesRegex(ValueError,'not available'):
            validate_forecast(f)

    def test_naive_timestamp_rejected(self):
        f = copy.deepcopy(self.forecast)
        f['asof']='2026-10-23T14:47:00'
        with self.assertRaisesRegex(ValueError,'timezone'):
            validate_forecast(f)

    def test_probability_sum_rejected(self):
        f = copy.deepcopy(self.forecast)
        f['runners'][0]['win_probability'] = 100
        with self.assertRaisesRegex(ValueError,'probability'):
            validate_forecast(f)

    def test_duplicate_runners_and_outcome_rejected(self):
        f = copy.deepcopy(self.forecast)
        f['runners'][0]['number']=2
        with self.assertRaisesRegex(ValueError,'duplicate'):
            validate_forecast(f)
        bad_result=copy.deepcopy(self.result)
        bad_result['finishing_order'][-1]=9
        with self.assertRaisesRegex(ValueError,'exactly'):
            validate_outcome(bad_result,self.forecast)

    def test_market_requires_full_field_and_is_observed_before_snapshot(self):
        quoted={"race_id":self.forecast['race_id'],
                "observed_at":"2026-10-23T14:00:00+09:00","source_url":"https://example.org/quote",
                "decimal_win_odds":{str(r['number']):10.0 for r in self.forecast['runners']}}
        expected=market_probabilities(quoted,self.forecast)
        self.assertAlmostEqual(sum(expected),1,places=12)
        self.assertAlmostEqual(expected[0],1/18,places=12)
        late=copy.deepcopy(quoted)
        late['observed_at']='2026-10-25T15:30:00+09:00'
        with self.assertRaisesRegex(ValueError,'lookahead'):
            validate_market(late,self.forecast)
        # An explicitly later decision-time quote may be evaluated even if the
        # independent model was frozen earlier (information windows differ).
        self.assertAlmostEqual(sum(market_probabilities(
            late,self.forecast,decision_at='2026-10-25T15:35:00+09:00')),1.)
        with self.assertRaisesRegex(ValueError,'before race start'):
            validate_market(late,self.forecast,decision_at='2026-10-25T16:00:00+09:00')
        missing=copy.deepcopy(quoted)
        del missing['decimal_win_odds']['4']
        with self.assertRaisesRegex(ValueError,'missing'):
            validate_market(missing,self.forecast)

    def test_calibration_cannot_fit_to_a_single_race(self):
        with self.assertRaisesRegex(ValueError,'Insufficient'):
            fit_exponent([(self.forecast,self.result)],min_train_races=30)
        w=walk_forward([(self.forecast,self.result)],min_train_races=30)
        self.assertIsNone(w[0]['calibrated'])
        self.assertEqual(w[0]['n_train_races'],0)

    def test_power_calibration_is_normalized(self):
        p = [r['win_probability'] for r in self.forecast['runners']]
        self.assertAlmostEqual(sum(power_calibrate(p,.5)),1,places=12)
        self.assertAlmostEqual(sum(power_calibrate(p,1.5)),1,places=12)
        self.assertAlmostEqual(power_calibrate(p,1)[8],p[8],places=12)

    @staticmethod
    def dummy_race(day, winner=1, result_known_next_day=True):
        f={"race_id":f"R{day}","race_at":f"2025-01-{day:02d}T15:40:00+09:00",
           "asof":f"2025-01-{day:02d}T09:00:00+09:00", "origin_source":"synthetic unit test",
           "runners":[{"number":1,"name":"A","win_probability":.6},
                      {"number":2,"name":"B","win_probability":.4}]}
        known=day+1 if result_known_next_day else 25
        o={"race_id":f"R{day}","status":"official_final","source_url":"https://example.org/unit-test",
           "finishing_order":[winner,3-winner],
           "result_usable_after":f"2025-01-{known:02d}T00:00:00+09:00"}
        return f,o

    def test_walk_forward_training_only_on_available_past(self):
        a=self.dummy_race(1)
        b=self.dummy_race(4,winner=2)
        c=self.dummy_race(8,winner=1)
        out=walk_forward([c,a,b],min_train_races=2)
        self.assertEqual([r['race_id'] for r in out],['R1','R4','R8'])
        self.assertEqual([r['n_train_races'] for r in out],[0,1,2])
        self.assertIsNone(out[1]['calibrated'])
        self.assertIsNotNone(out[2]['calibrated'])
        self.assertEqual(out[2]['calibrated']['training_races'],2)

    def test_walk_forward_delayed_results_excluded(self):
        a=self.dummy_race(1,result_known_next_day=False)
        b=self.dummy_race(4)
        c=self.dummy_race(8)
        out=walk_forward([a,b,c],min_train_races=2)
        self.assertEqual(out[2]['n_train_races'],1)
        self.assertIsNone(out[2]['calibrated'])

    def test_market_does_not_confuse_absolute_and_conditional_probability(self):
        # In a three-runner market 2/3/6x, the sum of inverse prices is >1.
        f={"race_id":"R3","asof":"2026-10-23T12:00:00+09:00",
           "race_at":"2026-10-24T15:00:00+09:00","origin_source":"unit fixture",
           "runners":[{"number":1,"name":"A","win_probability":.4},
                      {"number":2,"name":"B","win_probability":.4},
                      {"number":3,"name":"C","win_probability":.2}]}
        quote={"race_id":"R3","observed_at":"2026-10-23T11:00:00+09:00",
               "source_url":"https://example.org/price","decimal_win_odds":{"1":2.,"2":3.,"3":6.}}
        p=market_probabilities(quote,f)
        self.assertAlmostEqual(sum(p),1)
        self.assertAlmostEqual(p[0],.5,places=12)
        self.assertNotAlmostEqual(p[0],1./2. + 0.01)

if __name__ == '__main__':
    unittest.main()

class TestStatistics(unittest.TestCase):
    def test_reliability_one_race_has_one_observed_win(self):
        from keiba_backtest.diagnostics import reliability_bins,race_bootstrap_loss_difference
        root=Path(__file__).resolve().parents[1]
        f=load_json(root/'data/forecasts/2026_kikka_forecast.json')
        o=load_json(root/'data/outcomes/2026_kikka_result.json')
        bins=reliability_bins([(f,o)])
        self.assertEqual(sum(b['count'] for b in bins['bins']),18)
        self.assertEqual(sum(b['observed_wins'] for b in bins['bins']),1)
        self.assertAlmostEqual(sum(b['sum_forecast_probability'] for b in bins['bins']),1)
        self.assertEqual(race_bootstrap_loss_difference([(f,o)])['status'],'not_computed')

    def test_bootstrap_is_deterministic_at_race_level(self):
        from keiba_backtest.diagnostics import race_bootstrap_loss_difference
        f=load_json(ROOT/'data/forecasts/2026_kikka_forecast.json')
        o=load_json(ROOT/'data/outcomes/2026_kikka_result.json')
        f2=copy.deepcopy(f)
        o2=copy.deepcopy(o)
        f2['race_id']='synthetic_r2'
        o2['race_id']='synthetic_r2'
        r=[(f,o),(f2,o2)]
        # Unit test only: duplicate probability vectors with distinct synthetic
        # race IDs are NOT empirical independent evidence.
        a=race_bootstrap_loss_difference(r,min_races=2,n_resamples=101,seed=7)
        b=race_bootstrap_loss_difference(r,min_races=2,n_resamples=101,seed=7)
        self.assertEqual(a,b)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            race_bootstrap_loss_difference([(f,o),(f,o)],min_races=2,n_resamples=101)
