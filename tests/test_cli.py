from arek import cli


def test_adf_of_number_or_path():
    """1.0.6: --adf takes the disk number of local.conf (ADFN) or a path to an image."""
    from arek.cli import adf_of
    conf = {'ADF1': 'a/one.adf', 'ADF2': 'a/two.adf'}
    assert adf_of(conf, '1') == 'a/one.adf' and adf_of(conf, 2) == 'a/two.adf'
    assert adf_of(conf, 'local/x.ADF') == 'local/x.ADF'
    assert adf_of(conf, '9') is None
