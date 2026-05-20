import pandas as pd

from app.tools import price
from app.tools.price import AksharePriceAdapter


class FakeAkshare:
    def stock_info_a_code_name(self):
        raise RuntimeError("full mapping unavailable")

    def stock_info_sz_name_code(self):
        return pd.DataFrame([{"A股代码": "300750", "A股简称": "宁德时代"}])

    def stock_info_sh_name_code(self):
        raise RuntimeError("sh mapping unavailable")


def test_akshare_resolve_falls_back_to_exchange_mapping(monkeypatch):
    monkeypatch.setattr(price, "ak", FakeAkshare())

    instrument = AksharePriceAdapter().resolve("宁德时代")

    assert instrument is not None
    assert instrument.symbol == "sz300750"
    assert instrument.display_name == "宁德时代"


def test_akshare_resolve_uses_seed_mapping_before_network(monkeypatch):
    class BrokenAkshare:
        def stock_info_a_code_name(self):
            raise AssertionError("network mapping should not be called")

    monkeypatch.setattr(price, "ak", BrokenAkshare())

    instrument = AksharePriceAdapter().resolve("云天化")

    assert instrument is not None
    assert instrument.symbol == "sh600096"
    assert instrument.display_name == "云天化"


def test_akshare_resolve_handles_full_width_a_share_alias(monkeypatch):
    class BrokenAkshare:
        def stock_info_a_code_name(self):
            raise AssertionError("network mapping should not be called")

    monkeypatch.setattr(price, "ak", BrokenAkshare())

    instrument = AksharePriceAdapter().resolve("万科Ａ")

    assert instrument is not None
    assert instrument.symbol == "sz000002"
    assert instrument.display_name == "万科A"


def test_akshare_resolve_handles_full_company_name_for_seed(monkeypatch):
    class BrokenAkshare:
        def stock_info_a_code_name(self):
            raise AssertionError("network mapping should not be called")

    monkeypatch.setattr(price, "ak", BrokenAkshare())

    instrument = AksharePriceAdapter().resolve("利通电子股份有限公司")

    assert instrument is not None
    assert instrument.symbol == "sh603629"
    assert instrument.display_name == "利通电子"


def test_akshare_resolve_falls_back_to_spot_snapshot(monkeypatch):
    class SpotAkshare:
        def stock_info_a_code_name(self):
            raise RuntimeError("full mapping unavailable")

        def stock_info_sz_name_code(self):
            return pd.DataFrame()

        def stock_info_sh_name_code(self):
            raise RuntimeError("sh mapping unavailable")

        def stock_zh_a_spot(self):
            return pd.DataFrame(
                [
                    {"代码": "sh603986", "名称": "兆易创新"},
                    {"代码": "sz300750", "名称": "宁德时代"},
                ]
            )

    monkeypatch.setattr(price, "ak", SpotAkshare())

    instrument = AksharePriceAdapter().resolve("兆易创新")

    assert instrument is not None
    assert instrument.symbol == "sh603986"
    assert instrument.display_name == "兆易创新"
