from multiprocessing import Pool

from apply_engine.queue import load_queue, upsert_item


def _write(args):
    path, i = args
    for n in range(20):
        upsert_item(path, {"id": f"job-{i}", "n": n, "blob": "x" * 20000})


def test_parallel_upserts_keep_queue_valid(tmp_path):
    path = tmp_path / "queue.json"
    with Pool(6) as pool:
        pool.map(_write, [(path, i) for i in range(6)])
    items = load_queue(path)["items"]
    assert sorted(it["id"] for it in items) == [f"job-{i}" for i in range(6)]
    assert all(it["n"] == 19 for it in items)
