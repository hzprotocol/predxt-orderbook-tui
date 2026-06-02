from predxt_orderbook_tui.app import _parser


def test_parser_accepts_polymarket_asset():
    args = _parser().parse_args(["polymarket", "--asset-id", "123"])
    assert args.venue == "polymarket"
    assert args.asset_ids == ["123"]
