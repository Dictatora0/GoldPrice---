from run import parse_args


def test_parse_args_overrides():
    args = parse_args(["--port", "9000", "--interval", "5", "--no-notify"])

    assert args.port == 9000
    assert args.interval == 5
    assert args.no_notify is True
