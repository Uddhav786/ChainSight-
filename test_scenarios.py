"""End to end checks that every demo scenario tells its story.

    python -m unittest -v test_scenarios.py
Needs trained artifacts (prepare_data.py and train.py). Uses a separate database, so the demo DB is untouched.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

TMP_DB = Path(tempfile.gettempdir()) / "chainsight_scenario_test.db"
os.environ["CHAINSIGHT_DB"] = str(TMP_DB)
os.environ["LLM_BACKEND"] = "mock"

from config import ART_DIR  # noqa: E402


@unittest.skipUnless((ART_DIR / "models.joblib").exists(), "train the models first")
class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from replay import Engine
        eng = Engine(150)
        eng.open_db(reset=True)
        eng.run(speed=0, max_sleep=0)
        db = sqlite3.connect(TMP_DB)
        cls.alert, cls.all = {}, []
        rows = db.execute("""SELECT s.scenario, s.product_name, s.supplier_id, a.priority, a.verdict, a.recommended_action,
                                    a.options, a.requires_approval
                             FROM shipments s JOIN alerts a USING(shipment_id) WHERE s.scenario IS NOT NULL""").fetchall()
        for sc, name, sup, prio, verdict, action, opts, appr in rows:
            cls.alert[name] = a = {"scenario": sc, "supplier": sup, "priority": prio, "verdict": verdict, "action": action,
                               "options": [o["action"] for o in json.loads(opts)], "approval": appr}
            cls.all.append(a)
        cls.scores = dict(db.execute("SELECT supplier_id, score FROM suppliers").fetchall())
        cls.anoms = {k for (k,) in db.execute("SELECT kind FROM anomalies WHERE shipment_id > 900000")}
        cls.storm = json.loads(db.execute("SELECT value FROM meta WHERE key='last_disruption'").fetchone()[0])

    def test_s1_medicine_outranks_office_paper(self):
        self.assertGreater(self.alert["Insulin glargine 100 IU/mL vials"]["priority"],
                           3 * self.alert["A4 office paper, 10 reams"]["priority"])

    def test_s2_unreliable_supplier_ranks_higher(self):
        vac = [a for a in self.all if a["scenario"] == "S2"]
        quick = next(a for a in vac if a["supplier"] == "SUPM03")
        care = next(a for a in vac if a["supplier"] == "SUPM01")
        self.assertGreater(quick["priority"], care["priority"])
        self.assertIn("switch_supplier", quick["options"])

    def test_s3_newcomer_below_proven(self):
        self.assertGreater(self.scores["SUPM01"], self.scores["SUPM02"])

    def test_s4_cold_chain_triggers_replacement(self):
        a = self.alert["Insulin pens, prefilled (cold chain)"]
        self.assertIn("temperature_excursion", self.anoms)
        self.assertEqual(a["action"], "replace_shipment")
        self.assertEqual(a["approval"], 1)

    def test_s5_price_spike_flagged(self):
        self.assertIn("price_jump", self.anoms)
        self.assertIn("hold_invoice", self.alert["Artemether lumefantrine tablets (antimalarial)"]["options"])

    def test_s6_short_shipment_flagged(self):
        self.assertIn("quantity_mismatch", self.anoms)

    def test_s7_relief_outranks_general_in_storm(self):
        self.assertGreater(self.storm["affected"], 1)
        self.assertGreater(self.alert["Oral rehydration salts, relief kits"]["priority"],
                           self.alert["Folding chairs, set of 4"]["priority"])


if __name__ == "__main__":
    unittest.main()
