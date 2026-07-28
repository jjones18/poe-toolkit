import importlib.util
import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.filters import FilteringRuleEngine, RewardIncludeOverride, ValueRule
from core.valuation import NinjaPriceFetcher, PriceCache, PriceFetchResult
from services.price_service import PriceService

DUST_MODULE_PATH = SRC_DIR / "tools" / "league_tools" / "kalguur_dust" / "dust_data.py"
DUST_SPEC = importlib.util.spec_from_file_location("price_data_dust_data", DUST_MODULE_PATH)
assert DUST_SPEC is not None and DUST_SPEC.loader is not None
dust_data_module = importlib.util.module_from_spec(DUST_SPEC)
DUST_SPEC.loader.exec_module(dust_data_module)
DustDataCache = dust_data_module.DustDataCache
DustEfficiencyAnalyzer = dust_data_module.DustEfficiencyAnalyzer


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    def close(self):
        return None


class PriceCacheTests(unittest.TestCase):
    def test_concurrent_context_saves_preserve_every_keyed_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "prices.json"
            worker_count = 12
            barrier = threading.Barrier(worker_count)
            results = []

            class CoordinatedCache(PriceCache):
                def _read_store(self):
                    destination_existed = Path(self.cache_file).exists()
                    store = super()._read_store()
                    if not destination_existed:
                        try:
                            barrier.wait(timeout=0.5)
                        except threading.BrokenBarrierError:
                            pass
                    return store

            def save_context(index):
                cache = CoordinatedCache(
                    cache_file=cache_file,
                    game="poe1",
                    league=f"League-{index}",
                )
                results.append(cache.save(
                    {f"Item-{index}": float(index)},
                    {f"Item-{index}": "Currency"},
                ))

            threads = [
                threading.Thread(target=save_context, args=(index,))
                for index in range(worker_count)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(results, [True] * worker_count)
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["entries"]), worker_count)

    def test_cache_isolated_by_game_league_source_endpoint_set_and_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "prices.json"
            poe1 = PriceCache(
                game="poe1",
                league="Settlers",
                source="poe.ninja",
                endpoint_set="overview-v1",
                cache_file=cache_file,
            )
            poe2 = PriceCache(
                game="poe2",
                league="Standard",
                source="poe.ninja",
                endpoint_set="overview-v1",
                cache_file=cache_file,
            )

            self.assertTrue(poe1.save({"Chaos Orb": 1.0}, {"Chaos Orb": "Currency"}))
            self.assertIsNone(poe2.load())
            self.assertEqual(poe1.load()["prices"]["Chaos Orb"], 1.0)

            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], PriceCache.SCHEMA_VERSION)
            metadata = next(iter(payload["entries"].values()))["metadata"]
            self.assertEqual(metadata["game"], "poe1")
            self.assertEqual(metadata["league"], "Settlers")
            self.assertEqual(metadata["source"], "poe.ninja")
            self.assertEqual(metadata["endpoint_set"], "overview-v1")

    def test_cache_read_write_errors_are_guarded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "directory-as-cache"
            directory.mkdir()
            cache = PriceCache(game="poe1", league="Settlers", cache_file=directory)

            self.assertIsNone(cache.load())
            self.assertFalse(cache.save({"A": 1.0}, {"A": "Currency"}))
            self.assertIsNotNone(cache.last_error)

    def test_successful_v2_write_preserves_unkeyed_v1_cache_as_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "prices.json"
            legacy_bytes = json.dumps({
                "timestamp": "2026-01-01T00:00:00",
                "prices": {"Legacy": 7.0},
                "categories": {"Legacy": "Currency"},
            }).encode("utf-8")
            cache_file.write_bytes(legacy_bytes)
            cache = PriceCache(
                game="poe1",
                league="Settlers",
                cache_file=cache_file,
            )

            self.assertTrue(cache.save({"Current": 8.0}, {"Current": "Currency"}))

            backup = cache_file.with_name("prices.json.legacy-v1")
            self.assertEqual(backup.read_bytes(), legacy_bytes)
            self.assertEqual(cache.load()["prices"], {"Current": 8.0})


class PriceFetcherTests(unittest.TestCase):
    def make_cache(self, root, now):
        return PriceCache(
            game="poe1",
            league="Settlers",
            cache_file=Path(root) / "prices.json",
            now_provider=lambda: now,
        )

    def test_partial_fetch_is_explicit_bounded_and_does_not_replace_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = self.make_cache(temp_dir, datetime(2026, 7, 27, 12, 0, 0))
            session = FakeSession([
                {"lines": [{"currencyTypeName": "Chaos Orb", "chaosEquivalent": 1.0}]},
                OSError("endpoint unavailable"),
            ])
            fetcher = NinjaPriceFetcher(
                "Settlers",
                game="poe1",
                cache=cache,
                session=session,
                endpoints={
                    "Currency": "currencyoverview?type=Currency",
                    "Fragment": "currencyoverview?type=Fragment",
                },
                rate_limit_seconds=0,
            )

            result = fetcher.fetch_all_prices(force=True)

            self.assertEqual(result.status, "partial")
            self.assertEqual(result.failed_endpoints, ("Fragment",))
            self.assertEqual(fetcher.get_price("Chaos Orb"), 1.0)
            self.assertIsNone(cache.load(allow_stale=True))
            self.assertTrue(all(call[1]["timeout"] == 15 for call in session.calls))

    def test_total_failure_reports_failure_and_uses_stale_last_known_good(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_now = datetime(2026, 1, 1, 0, 0, 0)
            cache = self.make_cache(temp_dir, old_now)
            self.assertTrue(cache.save({"Old Item": 9.0}, {"Old Item": "Currency"}))
            cache.now_provider = lambda: datetime(2026, 7, 27, 12, 0, 0)
            session = FakeSession([OSError("offline")])
            fetcher = NinjaPriceFetcher(
                "Settlers",
                game="poe1",
                cache=cache,
                session=session,
                endpoints={"Currency": "currencyoverview?type=Currency"},
                rate_limit_seconds=0,
            )

            result = fetcher.fetch_all_prices(force=True)

            self.assertEqual(result.status, "failure")
            self.assertTrue(result.used_stale_cache)
            self.assertEqual(fetcher.get_price("Old Item"), 9.0)

    def test_unknown_and_known_zero_prices_remain_distinct(self):
        fetcher = NinjaPriceFetcher("Settlers", game="poe1", session=FakeSession([]))
        fetcher.prices = {"Known Zero": 0.0}

        self.assertEqual(fetcher.get_price("Known Zero"), 0.0)
        self.assertIsNone(fetcher.get_price("Missing"))


class PriceServiceTests(unittest.TestCase):
    def test_async_partial_result_keeps_existing_complete_snapshot(self):
        complete = Mock()
        complete.prices = {"Complete": 10.0}
        partial = Mock()
        partial.prices = {"Partial": 5.0}
        result = PriceFetchResult(
            status="partial", game="poe1", league="Settlers",
            source="poe.ninja", item_count=1,
            failed_endpoints=("Currency",),
        )
        service = PriceService(
            "poe1", "Settlers",
            worker_registry=Mock(),
        )
        service._fetcher = complete

        service._on_refresh_result(("poe1", "Settlers", partial, result))

        self.assertIs(service._fetcher, complete)
        partial.close.assert_called_once_with()
        complete.close.assert_not_called()
        self.assertIs(service.last_result, result)

    def test_context_change_cancels_inflight_async_refresh(self):
        registry = Mock()
        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=Mock(),
            worker_registry=registry,
        )

        self.assertTrue(service.set_context("poe1", "Standard"))

        registry.cancel.assert_called_once_with("price-refresh")

    def test_active_refresh_context_tracks_until_finished_and_clears_on_success(self):
        callbacks = {}

        def capture_start(name, operation, **kwargs):
            callbacks.update(kwargs)
            return True

        registry = Mock()
        registry.start.side_effect = capture_start
        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=Mock(),
            worker_registry=registry,
        )

        self.assertTrue(service.refresh_prices())
        self.assertEqual(service.active_refresh_context(), ("poe1", "Settlers"))

        callbacks["on_finished"]()

        self.assertIsNone(service.active_refresh_context())

    def test_active_refresh_context_clears_on_error_and_cancel(self):
        callbacks = {}

        def capture_start(name, operation, **kwargs):
            callbacks.update(kwargs)
            return True

        registry = Mock()
        registry.start.side_effect = capture_start
        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=Mock(),
            worker_registry=registry,
        )

        self.assertTrue(service.refresh_prices())
        self.assertEqual(service.active_refresh_context(), ("poe1", "Settlers"))
        callbacks["on_error"](RuntimeError("offline"))
        self.assertEqual(service.active_refresh_context(), ("poe1", "Settlers"))
        callbacks["on_finished"]()
        self.assertIsNone(service.active_refresh_context())

        service.set_context("poe1", "Standard")
        self.assertTrue(service.refresh_prices())
        self.assertEqual(service.active_refresh_context(), ("poe1", "Standard"))
        callbacks["on_cancelled"]()
        self.assertEqual(service.active_refresh_context(), ("poe1", "Standard"))
        callbacks["on_finished"]()
        self.assertIsNone(service.active_refresh_context())

    def test_refresh_operation_closes_fetcher_when_fetch_raises(self):
        captured = {}
        registry = Mock()

        def capture_start(name, operation, **callbacks):
            captured["operation"] = operation
            return True

        registry.start.side_effect = capture_start

        class FailingFetcher:
            def __init__(self, league, game):
                self.closed = False

            def fetch_all_prices(self, force=False, context=None):
                raise RuntimeError("fetch failed")

            def close(self):
                self.closed = True

        created = []

        def factory(league, game):
            fetcher = FailingFetcher(league, game)
            created.append(fetcher)
            return fetcher

        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=factory,
            worker_registry=registry,
        )
        self.assertTrue(service.refresh_prices())

        with self.assertRaisesRegex(RuntimeError, "fetch failed"):
            captured["operation"](Mock())
        self.assertTrue(created[0].closed)

    def test_partial_force_refresh_keeps_existing_complete_snapshot(self):
        class FakeFetcher:
            def __init__(self, league, game, result, prices):
                self.league = league
                self.game = game
                self.result = result
                self.prices = prices
                self.closed = False

            def fetch_all_prices(self, force=False, context=None):
                return self.result

            def get_price(self, name):
                return self.prices.get(name)

            def close(self):
                self.closed = True

        complete = FakeFetcher(
            "Settlers", "poe1",
            PriceFetchResult(
                status="success", game="poe1", league="Settlers",
                source="poe.ninja", item_count=1,
            ),
            {"Complete": 10.0},
        )
        partial = FakeFetcher(
            "Settlers", "poe1",
            PriceFetchResult(
                status="partial", game="poe1", league="Settlers",
                source="poe.ninja", item_count=1,
                failed_endpoints=("Currency",),
            ),
            {"Partial": 5.0},
        )
        created = iter([complete, partial])
        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=lambda league, game: next(created),
            worker_registry=Mock(),
        )

        self.assertIs(service.get_fetcher(), complete)
        self.assertIs(service.get_fetcher(force=True), complete)
        self.assertTrue(partial.closed)
        self.assertEqual(service.last_result.status, "partial")

    def test_empty_total_failure_is_not_retained_and_next_read_retries(self):
        class FakeFetcher:
            def __init__(self, result, prices):
                self.result = result
                self.prices = prices
                self.closed = False

            def fetch_all_prices(self, force=False, context=None):
                return self.result

            def get_price(self, name):
                return self.prices.get(name)

            def close(self):
                self.closed = True

        failed = FakeFetcher(
            PriceFetchResult(
                status="failure", game="poe1", league="Settlers",
                source="poe.ninja", item_count=0, detail="offline",
            ),
            {},
        )
        recovered = FakeFetcher(
            PriceFetchResult(
                status="success", game="poe1", league="Settlers",
                source="poe.ninja", item_count=1,
            ),
            {"Chaos Orb": 1.0},
        )
        created = iter([failed, recovered])
        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=lambda league, game: next(created),
            worker_registry=Mock(),
        )

        self.assertIs(service.get_fetcher(), failed)
        self.assertTrue(failed.closed)
        self.assertIs(service.get_fetcher(), recovered)
        self.assertIs(service.get_fetcher(), recovered)
        self.assertEqual(service.get_price("Chaos Orb"), 1.0)

    def test_context_change_does_not_wait_for_synchronous_price_request(self):
        started = threading.Event()
        release = threading.Event()
        changed = threading.Event()
        loader_errors = []

        class BlockingFetcher:
            def __init__(self, league, game):
                self.league = league
                self.game = game
                self.prices = {"Chaos Orb": 1.0}
                self.closed = False

            def fetch_all_prices(self, force=False, context=None):
                started.set()
                release.wait(1)
                return PriceFetchResult(
                    status="success", game=self.game, league=self.league,
                    source="poe.ninja", item_count=1,
                )

            def close(self):
                self.closed = True

        service = PriceService(
            "poe1", "Settlers",
            fetcher_factory=BlockingFetcher,
            worker_registry=Mock(),
        )

        def load_prices():
            try:
                service.get_fetcher()
            except Exception as error:
                loader_errors.append(error)

        loader = threading.Thread(target=load_prices)
        loader.start()
        self.assertTrue(started.wait(0.2))
        changer = threading.Thread(target=lambda: (
            service.set_context("poe1", "Standard"), changed.set()
        ))
        changer.start()
        try:
            self.assertTrue(changed.wait(0.2))
        finally:
            release.set()
            loader.join(2)
            changer.join(2)
        self.assertFalse(loader_errors)

    def test_context_change_invalidates_active_fetcher_and_reuses_matching_context(self):
        created = []

        class FakeFetcher:
            def __init__(self, league, game):
                self.league = league
                self.game = game
                self.prices = {"Chaos Orb": 1.0}

            def fetch_all_prices(self, force=False, context=None):
                return Mock(status="success")

            def get_price(self, name):
                return self.prices.get(name)

        def factory(league, game):
            fetcher = FakeFetcher(league, game)
            created.append(fetcher)
            return fetcher

        service = PriceService(
            game="poe1",
            league="Settlers",
            fetcher_factory=factory,
        )
        first = service.get_fetcher()
        self.assertIs(service.get_fetcher(), first)

        service.set_context("poe1", "Standard")
        second = service.get_fetcher()

        self.assertIsNot(first, second)
        self.assertEqual((second.game, second.league), ("poe1", "Standard"))
        self.assertEqual(len(created), 2)


class UnknownPriceHandlingTests(unittest.TestCase):
    def test_explicit_reward_override_still_accepts_unknown_price(self):
        prices = Mock()
        prices.get_price.return_value = None
        engine = FilteringRuleEngine()
        engine.add_rule(ValueRule(min_profit=1))
        engine.add_override(RewardIncludeOverride(["Included Reward"]))

        self.assertTrue(engine.evaluate({
            "sacrifice": "Unknown Cost",
            "sacrifice_count": 1,
            "reward": "Included Reward",
            "reward_count": 1,
        }, prices))

    def test_filter_engine_excludes_unknown_prices_by_default(self):
        prices = Mock()
        prices.get_price.side_effect = lambda name: {"Known": 10.0}.get(name)
        engine = FilteringRuleEngine()
        engine.add_rule(ValueRule(min_profit=1))
        item = {
            "sacrifice": "Missing",
            "sacrifice_count": 1,
            "reward": "Known",
            "reward_count": 1,
        }

        self.assertFalse(engine.evaluate(item, prices))

    def test_dust_efficiency_never_maps_unknown_or_zero_price_to_infinity(self):
        dust_fetcher = Mock()
        dust_fetcher.calculate_item_dust.return_value = (100, 120)
        price_fetcher = Mock()
        analyzer = DustEfficiencyAnalyzer(dust_fetcher, price_fetcher)

        price_fetcher.get_price.return_value = None
        unknown = analyzer.get_efficiency("Unknown")
        price_fetcher.get_price.return_value = 0.0
        zero = analyzer.get_efficiency("Zero")

        self.assertIsNone(unknown["chaos_price"])
        self.assertIsNone(unknown["efficiency"])
        self.assertFalse(unknown["price_known"])
        self.assertEqual(zero["chaos_price"], 0.0)
        self.assertIsNone(zero["efficiency"])
        self.assertTrue(zero["price_known"])


class DustProvenanceTests(unittest.TestCase):
    def test_successful_v2_write_preserves_unversioned_dust_cache_as_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "dust.json"
            legacy_bytes = json.dumps({
                "timestamp": "2026-01-01T00:00:00",
                "dust_values": {"Legacy": {"base_dust": 10}},
            }).encode("utf-8")
            cache_file.write_bytes(legacy_bytes)
            cache = DustDataCache(
                cache_file,
                game="poe1",
                league="Settlers",
            )

            self.assertTrue(cache.save(
                {"Current": {"base_dust": 20}},
                source="test",
            ))

            backup = cache_file.with_name("dust.json.legacy-v1")
            self.assertEqual(backup.read_bytes(), legacy_bytes)
            self.assertEqual(cache.load()["dust_values"], {"Current": {"base_dust": 20}})

    def test_dust_cache_validates_schema_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "dust.json"
            cache = DustDataCache(
                cache_file,
                game="poe1",
                league="Settlers",
                now_provider=lambda: datetime(2026, 7, 27, 12, 0, 0),
            )
            dust_values = {
                "Example": {
                    "base_dust": 10,
                    "dust_ilvl84": 10,
                    "dust_ilvl84_q20": 12,
                    "item_type": "Ring",
                }
            }

            self.assertTrue(cache.save(
                dust_values,
                source="bundled-poedust-2025",
                estimated=True,
                source_timestamp="2025-01-01T00:00:00",
            ))
            loaded = cache.load()

            self.assertEqual(loaded["dust_values"], dust_values)
            self.assertEqual(loaded["metadata"]["source"], "bundled-poedust-2025")
            self.assertTrue(loaded["metadata"]["estimated"])
            self.assertEqual(loaded["metadata"]["schema_version"], DustDataCache.SCHEMA_VERSION)

            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            payload["dust_values"]["Example"]["base_dust"] = "not-a-number"
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(cache.load())

    def test_bundled_fallback_is_labeled_stale_estimated_and_dated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = DustDataCache(
                Path(temp_dir) / "dust.json",
                game="poe1",
                league="Settlers",
            )
            fetcher = dust_data_module.DustDataFetcher("Settlers", cache=cache)
            fetcher.session.get = Mock(side_effect=OSError("offline"))

            self.assertTrue(fetcher.fetch_dust_data())

            loaded = cache.load(allow_stale=True)
            self.assertEqual(loaded["metadata"]["source"], "bundled-poedust")
            self.assertEqual(loaded["metadata"]["source_timestamp"], "2025-01-26")
            self.assertTrue(loaded["metadata"]["estimated"])
            self.assertEqual(fetcher.provenance["status"], "stale fallback")


if __name__ == "__main__":
    unittest.main()
