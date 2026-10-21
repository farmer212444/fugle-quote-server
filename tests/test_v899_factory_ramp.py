import copy
from datetime import datetime
import hashlib
from pathlib import Path
import tempfile
import unittest

from tw_model_v880.factory_ramp import accounting_only, assess_factory_ramp
from scripts.v899_factory_ramp_audit import standalone, render


def snap(*,revenue=1000.,variable=.45,fixed=.15,good=800.,cap=1000.,sold=800.,
         inv=None,yield_rate=.90):
    var=revenue*variable
    f=revenue*fixed
    return dict(revenue_twd=revenue,gross_profit_twd=revenue-var-f,
        material_cogs_twd=var*.6,labor_cogs_twd=var*.25,other_variable_cogs_twd=var*.15,
        fixed_manufacturing_cogs_twd=f,units_sold=sold,good_units_produced=good,
        capacity_units=cap,yield_rate=yield_rate,
        inventory_delta_good_units=good-sold if inv is None else inv)


def fixture(td,prior=None,current=None):
    root=Path(td)
    originals=root/"originals"
    originals.mkdir()
    docs=[]
    for index,payload in enumerate((b"independently archived prior issuer original",b"independently archived recent issuer original")):
        name=f"issuer_source_{index}.pdf"
        (originals/name).write_bytes(payload)
        docs.append(dict(url=f"https://www.example.com/issuer/{name}",
                         available_at="2026-08-20T12:00:00+08:00",
                         verified_at="2026-10-19T12:00:00+08:00",
                         original_publisher_verified=True,sha256=hashlib.sha256(payload).hexdigest(),
                         relative_original_path=name))
    old=prior or snap()
    new=current or snap(revenue=1200,variable=.44,fixed=.13,good=950,sold=950)
    c=dict(code="9802",scope="CONSOLIDATED_MATCHED_PRODUCT_UNITS",
        periods={"prior_comparable":"2025-Q2","current":"2026-Q2"},
        complete_product_mix_and_cost_allocation_verified=True,
        inventory_cost_recognition_verified=True,product_unit_definition_unchanged=True,
        original_sources=docs,observations={"prior_comparable":old,"current":new})
    accounting={key:{k:x[k] for k in ("revenue_twd","gross_profit_twd")} for key,x in c["observations"].items()}
    return c,accounting,originals


class FactoryRampCostBridgeTests(unittest.TestCase):
    ASOF="2026-10-21T13:00:00+08:00"

    def audit(self,prior=None,current=None):
        with tempfile.TemporaryDirectory() as td:
            c,acc,originals=fixture(td,prior,current)
            return assess_factory_ramp(c,asof=self.ASOF,archive_root=originals,accounting=acc)

    def test_synthetic_plant_recovers_fixed_cost_absorption(self):
        out=self.audit()
        self.assertEqual(out["status"],"RAMP_ABSORPTION_RECOVERY_CONSISTENT")
        self.assertAlmostEqual(out["gross_margin_delta_pp"],3)
        self.assertAlmostEqual(out["fixed_absorption_offset_pp"],2)
        self.assertAlmostEqual(out["variable_cost_and_mix_offset_pp"],1)
        self.assertAlmostEqual(out["utilization_change_pp"],15)
        self.assertFalse(out["base_gm_override_allowed"])
        self.assertFalse(out["formal_a_plus_changed"])
        self.assertFalse(out["quarterly_plant_learning_curve_causally_proven"])

    def test_synthetic_fixed_cost_dilution(self):
        before=snap(good=900,sold=900)
        current=snap(revenue=1000,variable=.45,fixed=.22,good=700,sold=700)
        self.assertEqual(self.audit(before,current)["status"],"RAMP_FIXED_COST_DILUTION_CONSISTENT")

    def test_synthetic_variable_cost_worsens_even_if_utilization_stable(self):
        before=snap(good=900,sold=900)
        current=snap(revenue=1000,variable=.56,fixed=.15,good=900,sold=900)
        out=self.audit(before,current)
        self.assertEqual(out["status"],"VARIABLE_COST_OR_PRICING_PRESSURE_CONSISTENT")
        self.assertFalse(out["structural_cost_pressure_causally_proven"])

    def test_high_margin_rising_does_not_prove_new_plant_cost_zero(self):
        before=snap(revenue=1000,variable=.25,fixed=.15,good=900,sold=900)
        current=snap(revenue=1000,variable=.20,fixed=.17,good=880,sold=880)
        out=self.audit(before,current)
        self.assertEqual(out["status"],"RAMP_DILUTION_MASKED_BY_OTHER_IMPROVEMENTS")
        self.assertAlmostEqual(out["gross_margin_delta_pp"],3)
        self.assertAlmostEqual(out["fixed_cost_burden_change_pp"],2)

    def test_negative_inventory_delta_is_legitimate_if_reconciled(self):
        old=snap(good=750,sold=800)
        self.assertEqual(self.audit(prior=old)["status"],"RAMP_ABSORPTION_RECOVERY_CONSISTENT")

    def test_invalid_original_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            case,acc,archive=fixture(td)
            case["original_sources"][0]["sha256"]="a"*64
            with self.assertRaisesRegex(ValueError,"ORIGINAL_SHA_MISMATCH"):
                assess_factory_ramp(case,asof=self.ASOF,archive_root=archive,accounting=acc)

    def test_unarchived_original_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            case,acc,archive=fixture(td)
            (archive/"issuer_source_0.pdf").unlink()
            with self.assertRaisesRegex(ValueError,"ORIGINAL_PATH_INVALID"):
                assess_factory_ramp(case,asof=self.ASOF,archive_root=archive,accounting=acc)

    def test_path_traversal_cannot_substitute_external_original(self):
        with tempfile.TemporaryDirectory() as td:
            case,acc,archive=fixture(td)
            case["original_sources"][0]["relative_original_path"]="../../some_other_file"
            with self.assertRaisesRegex(ValueError,"ORIGINAL_PATH_INVALID"):
                assess_factory_ramp(case,asof=self.ASOF,archive_root=archive,accounting=acc)

    def test_future_available_or_verified_source_rejected(self):
        for key,value in [("available_at","2026-10-22T00:00:00+08:00"),
                          ("verified_at","2026-10-23T12:00:00+08:00"),
                          ("verified_at","2026-08-01T09:00:00+08:00")]:
            with self.subTest(key=key,value=value),tempfile.TemporaryDirectory() as td:
                c,acc,a=fixture(td)
                c["original_sources"][0][key]=value
                with self.assertRaisesRegex(ValueError,"PIT_OR_VERIFICATION"):
                    assess_factory_ramp(c,asof=self.ASOF,archive_root=a,accounting=acc)

    def test_untrusted_source_and_unverified_scope_refused(self):
        for key,val in [("scope","SOME_ONE_FACTORIES_ONLY"),
                        ("complete_product_mix_and_cost_allocation_verified",False),
                        ("inventory_cost_recognition_verified",False),
                        ("product_unit_definition_unchanged",False)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as td:
                c,acc,a=fixture(td);c[key]=val
                with self.assertRaises(ValueError):
                    assess_factory_ramp(c,asof=self.ASOF,archive_root=a,accounting=acc)

    def test_declared_costs_must_add_to_reported_gross_profit(self):
        with tempfile.TemporaryDirectory() as td:
            c,acc,a=fixture(td)
            c["observations"]["current"]["fixed_manufacturing_cogs_twd"]+=100
            with self.assertRaisesRegex(ValueError,"REVENUE_COGS_BRIDGE"):
                assess_factory_ramp(c,asof=self.ASOF,archive_root=a,accounting=acc)

    def test_consolidated_accounts_must_reconcile_with_issuer_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            c,acc,a=fixture(td)
            acc["current"]["revenue_twd"]*=1.1
            with self.assertRaisesRegex(ValueError,"ACCOUNTING_ORIGINAL_MIRROR"):
                assess_factory_ramp(c,asof=self.ASOF,archive_root=a,accounting=acc)

    def test_fake_factory_yield_or_double_count_inventory_rejected(self):
        for field,value in [("yield_rate",1.4),("capacity_units",500),("inventory_delta_good_units",300)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as td:
                c,acc,a=fixture(td)
                c["observations"]["current"][field]=value
                with self.assertRaises(ValueError):
                    assess_factory_ramp(c,asof=self.ASOF,archive_root=a,accounting=acc)

    def test_missing_cost_fields_and_false_positive_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            c,acc,a=fixture(td)
            del c["observations"]["current"]["material_cogs_twd"]
            with self.assertRaisesRegex(ValueError,"NONFINITE_OR_MISSING"):
                assess_factory_ramp(c,asof=self.ASOF,archive_root=a,accounting=acc)

    def test_accounting_only_never_automatically_attributes_causes(self):
        a={"revenue_twd":1e9,"gross_profit_twd":2e8,"operating_profit_twd":1e8}
        b={"revenue_twd":1.1e9,"gross_profit_twd":1.4e8,"operating_profit_twd":1e7}
        x=accounting_only("9802",a,b,current_period="2026-Q2",
                          comparable_period="2025-Q2",source="SYNTHETIC")
        self.assertEqual(x["status"],"OBSERVED_MARGIN_DECLINE_CAUSE_UNVERIFIED")
        self.assertEqual(x["classification_plant_ramp_vs_structural"],"INSUFFICIENT_ORIGINAL_CAUSAL_EVIDENCE")
        self.assertFalse(x["base_gm_override_allowed"])
        self.assertFalse(x["formal_a_plus_changed"])

    def test_quarterly_ytd_delta_not_accidental_h1_margin(self):
        q1=dict(market="TWSE",code="9802",unit="NTD_thousands_except_EPS",
                year_to_date_values=True,revenue_ytd_k=3000,gross_profit_ytd_k=600,
                operating_profit_ytd_k=100)
        q2=dict(q1,revenue_ytd_k=8000,gross_profit_ytd_k=1200,operating_profit_ytd_k=200)
        r=standalone(q1,q2)
        self.assertEqual(r["revenue_twd"],5000000)
        self.assertEqual(r["gross_profit_twd"],600000)
        self.assertEqual(r["operating_profit_twd"],100000)

    def test_future_quarter_disclosure_cannot_turn_into_old_pit(self):
        from scripts.v899_factory_ramp_audit import _time
        with self.assertRaisesRegex(ValueError,"TIMEZONE"):
            _time("2026-10-21T12:00:00")


if __name__=="__main__":
    unittest.main()
