import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from highland.normalize import infer_trim, is_highland, resolve_year, valid_vin, vin_year


def t(year, raw, dt=None, hp=None, vin=None):
    return infer_trim(year, raw, dt, hp, vin)[0]


def test_carmax_strings():
    assert t(2024, "Long Range", "RWD", 295, "5YJ3E1EA2RF828748") == "Long Range RWD"
    assert t(2024, "Long Range", "AWD", None, "5YJ3E1EB4RF860559") == "Long Range AWD"
    assert t(2024, None, "RWD", 271, "5YJ3E1EA5RF788729") == "RWD"
    assert t(2026, "Premium", "RWD", 295, "5YJ3E1EA7TF146360") == "Long Range RWD"
    assert t(2025, "Performance", "AWD", 510, "5YJ3E1EC1SF000000") == "Performance"


def test_tesla_strings():
    assert t(2025, "Model 3 Premium Rear-Wheel Drive") == "Long Range RWD"
    assert t(2024, "Long Range All-Wheel Drive") == "Long Range AWD"
    assert t(2024, "Performance All-Wheel Drive ") == "Performance"
    assert t(2024, "Model 3 Rear-Wheel Drive") == "RWD"
    assert t(2026, "Model 3 Standard Rear-Wheel Drive") == "Standard"
    assert t(2024, "Standard Range Rear-Wheel Drive") == "RWD"


def test_vin_codes_win():
    assert t(2024, "", None, None, "5YJ3E1EC5RF000001") == "Performance"
    assert t(2024, "", None, None, "5YJ3E1EB5RF000001") == "Long Range AWD"


def test_defaults_and_confidence():
    trim, conf = infer_trim(2025, "RWD")
    assert trim == "Long Range RWD" and conf == "low"
    trim, conf = infer_trim(2024, "RWD")
    assert trim == "RWD" and conf == "low"


def test_vin_helpers():
    assert valid_vin("5YJ3E1EA7TF146360")
    assert not valid_vin("5YJ3E1EA7TF14636O")  # letter O is not allowed
    assert vin_year("5YJ3E1EA7TF146360") == 2026
    assert resolve_year(2025, "5YJ3E1EA7TF146360") == (2026, "source said 2025, VIN decodes to 2026")
    assert is_highland(2024, "5YJ3E1EA7RF146360")
    assert not is_highland(2023, "5YJ3E1EA7PF146360")
    assert not is_highland(2024, "7SAYGDEE7RA287118")  # Model Y VIN
