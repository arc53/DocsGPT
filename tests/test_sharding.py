"""``pytest --shard INDEX/TOTAL`` splits the suite across CI jobs."""

from __future__ import annotations

import pytest

from tests.sharding import assign_shards, parse_shard

pytest_plugins = ["pytester"]


@pytest.mark.unit
class TestParseShard:
    def test_reads_index_and_total(self):
        assert parse_shard("2/3") == (2, 3)

    @pytest.mark.parametrize("value", ["0/3", "4/3", "3", "a/b", "1/2/3", ""])
    def test_refuses_anything_else(self, value):
        with pytest.raises(ValueError, match="--shard"):
            parse_shard(value)


@pytest.mark.unit
class TestAssignShards:
    FILES = ["a.py"] * 50 + ["b.py"] * 30 + ["c.py"] * 20 + ["d.py"] * 10 + ["e.py"] * 5

    def test_every_file_lands_in_exactly_one_shard(self):
        shards = assign_shards(self.FILES, 3)

        assert set(shards) == {"a.py", "b.py", "c.py", "d.py", "e.py"}
        assert set(shards.values()) == {1, 2, 3}

    def test_shards_hold_about_the_same_number_of_tests(self):
        shards = assign_shards(self.FILES, 3)
        loads = [sum(1 for file in self.FILES if shards[file] == shard) for shard in (1, 2, 3)]

        # 115 tests: the largest file alone is 50, so 50 / 35 / 30 is the best deal.
        assert sorted(loads) == [30, 35, 50]

    def test_the_deal_does_not_depend_on_collection_order(self):
        assert assign_shards(self.FILES, 3) == assign_shards(list(reversed(self.FILES)), 3)

    def test_one_shard_takes_everything(self):
        assert set(assign_shards(self.FILES, 1).values()) == {1}


@pytest.mark.unit
class TestShardOption:
    @pytest.fixture()
    def suite(self, pytester):
        pytester.makeconftest(
            """
            def pytest_addoption(parser):
                parser.addoption("--shard", default=None)

            def pytest_collection_modifyitems(config, items):
                from tests.conftest import _keep_shard
                _keep_shard(config, items)
            """
        )
        pytester.makepyfile(
            test_one="def test_a(): pass\ndef test_b(): pass\ndef test_c(): pass\n",
            test_two="def test_d(): pass\ndef test_e(): pass\n",
            test_three="def test_f(): pass\n",
        )
        return pytester

    def test_the_shards_cover_the_suite_without_overlap(self, suite):
        ran = []
        for index in (1, 2):
            result = suite.runpytest_inprocess(f"--shard={index}/2", "-q", "-p", "no:cacheprovider")
            ran.append(result.parseoutcomes())

        assert [outcome["passed"] for outcome in ran] == [3, 3]
        assert [outcome["deselected"] for outcome in ran] == [3, 3]

    def test_no_option_runs_everything(self, suite):
        assert suite.runpytest_inprocess("-q", "-p", "no:cacheprovider").parseoutcomes() == {"passed": 6}

    def test_a_bad_value_is_a_usage_error(self, suite):
        result = suite.runpytest_inprocess("--shard=3/2", "-p", "no:cacheprovider")

        assert result.ret == pytest.ExitCode.USAGE_ERROR
