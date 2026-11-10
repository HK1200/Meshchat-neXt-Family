import importlib.util
from pathlib import Path
import pytest

source = Path(__file__).resolve().parents[1] / "app/src/main/python/family_radios.py"
spec = importlib.util.spec_from_file_location("family_radio_frequency", source)
radios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(radios)


@pytest.mark.parametrize("frequency", [
    "914.875", "914.875 MHz", "914875", "914875 kHz", "914,875 kHz",
    "914875000", "914875000 Hz", "914,875,000 Hz", "914,875 MHz",
])
def test_frequency_units_preserve_exact_radio_profile(frequency):
    config = radios.validate({
        "enabled": True, "transport": "tcp", "endpoint": "192.168.1.100",
        "frequency": frequency, "bandwidth": 125, "sf": 8, "cr": 7, "power": 17,
    })
    assert config["frequency"] == 914875000
    assert radios.public(config)["frequency"] == 914.875


@pytest.mark.parametrize("frequency", ["1021 MHz", "136999999 Hz", "915.0000001 MHz", "915 GHz", "", None])
def test_frequency_reports_clear_range_and_units(frequency):
    with pytest.raises(ValueError, match="137 to 1020 MHz"):
        radios.frequency_hz(frequency)
